# ArangoDB to Postgres ETL for LEO CDP

This DAG performs an **hourly Extract, Transform, and Load (ETL)** process to synchronize customer and transaction data from an ArangoDB `LEO CDP` instance into a PostgreSQL database, likely used for analytics or RAG applications.

The process enriches the data by generating **vector embeddings** for profiles and transactions before loading them into `pgvector`-enabled tables.

---

## Core Logic

The DAG flow is as follows:

### 1. Extract Profiles (`extract_profiles`)
- Fetches a list of profile documents from the ArangoDB `cdp_profile` collection.
- Filtering is based on a `segment_id` provided as a DAG run parameter. Only profiles belonging to this segment are extracted.
- If no `segment_id` is provided, the DAG run will be **short-circuited** (no profiles or transactions will be processed).

### 2. Extract Transactions (`extract_transactions`)
- Based on the `_keys` of the profiles extracted in step 1, this task fetches all associated transaction documents from the `cdp_profile2conversion` edge collection.

### 3. Transform & Embed (`transform_and_embed_profiles`, `transform_and_embed_txns`)
- These two **parallel tasks** process the raw JSON documents.
- **Transformation:** Maps ArangoDB fields (e.g., `primaryEmail`, `transactionValue`) to corresponding PostgreSQL table columns (e.g., `email`, `amount`). The original ArangoDB document is preserved as a `JSONB` string in the `metadata` or `context_data` column.
- **Embedding:** A text summary is composed for each profile and transaction. This text is sent to an embedding model (loaded via `get_embeddings_batch`) in batches. The resulting vector (a list of floats) is prepared for storage.

### 4. Load (`load_profiles_to_pg`, `load_txns_to_pg`)
- These two **parallel tasks** load the transformed data into PostgreSQL using `psycopg`'s `executemany` for high-performance bulk operations.
- An **ON CONFLICT DO UPDATE (UPSERT)** command is used to insert new records or update existing ones based on their primary keys:
  - `cdp_profile_id` for profiles
  - Composite key `(tenant_id, user_id, txn_id)` for transactions

### 5. Refresh Metrics (`refresh_metrics_task`)
- After both load tasks are complete:
  - Identifies all unique `tenant_ids` from the processed profiles.
  - Executes the PostgreSQL function:
    ```sql
    SELECT refresh_customer_metrics(%s);
    ```
    for each unique tenant. Likely updates materialized views or summary tables.

---

## Configuration

### Airflow Connections
- **`arango_conn`**: An Airflow connection of type HTTP  
  - Host: The ArangoDB coordinator URL (e.g., `http://arango-host:8529`)  
  - Login: ArangoDB username  
  - Password: ArangoDB password  

- **`pg_conn`**: An Airflow connection of type Postgres  
  - All standard fields (Host, Schema, Login, Password, Port) are used to construct a DSN for `psycopg`.

### Airflow Variables
- `arango_db`: ArangoDB database name (default: `leo_cdp`)  
- `arango_profile_collection`: Profile collection name (default: `cdp_profile`)  
- `arango_txn_collection`: Transaction/edge collection name (default: `cdp_profile2conversion`)  
- `embed_batch_size`: Number of texts sent to the embedding model in a single batch (default: 64)  
- `embedding_provider`: Hosted embedding provider (`"google"`, `"openai"`, or `"openrouter"`)
- `embed_model_id`: Provider-specific hosted embedding model ID

### DAG Parameters
- **`segment_id` (string):** ID of the LEO CDP segment to process.  
  - If left blank, the DAG will run but process **0 records**.
