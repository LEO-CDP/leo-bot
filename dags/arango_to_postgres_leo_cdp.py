"""
Airflow DAG: ArangoDB -> Postgres ETL for LEO CDP
- Extract customer profiles & transactional events
- Batch embeddings (placeholder)
- Upsert into customer_profile and transactional_context
- Call refresh_customer_metrics per tenant
Notes:
- Replace `get_embeddings_batch` with your real provider (OpenAI, Vertex, etc).
- Store secrets (API keys) in Connections or a secret backend, not in Variables.
"""

from datetime import datetime, timedelta
import json
import logging
from typing import List, Dict, Any, Iterable, TypedDict, Optional

from airflow import DAG
from airflow.decorators import task
from airflow.models import Variable
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.arangodb.hooks.arangodb import ArangoDBHook
from airflow.models.param import Param
from airflow.exceptions import AirflowException # Import for raising errors


# external libs
import psycopg  # psycopg3
from leoai.ai_core import get_embedding_model

# ---------------------------
# CONFIG
# ---------------------------
DEFAULT_ARGS = {
    'owner': 'leo_cdp',
    'depends_on_past': False,
    'email_on_failure': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# --- Connections & Variables ---
ARANGO_CONN_ID = 'leo_cdp_arangodb'
PG_CONN_ID = 'leo_bot_pgsql'

# 
EMBED_BATCH_SIZE = int(Variable.get("embed_batch_size", default_var=64))
ARANGO_PROFILE_COL = Variable.get("arango_profile_collection", default_var="cdp_profile")
ARANGO_TXN_COL = Variable.get("arango_txn_collection", default_var="cdp_profile2conversion")


# --- Static Config ---
DATA_SOURCE_TAG = 'arango_ingest' # For updated_by columns

# logging
log = logging.getLogger("airflow.task")
logging.basicConfig(level=logging.INFO)

def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Create normalized embeddings using the configured hosted API provider.
    Returns list of vectors (length == dim) for each text.
    """
    if not texts:
        return []

    embeddings = get_embedding_model().encode(
        texts,
        batch_size=16,
        normalize_embeddings=True,
    )
    return embeddings.tolist()


# ---------------------------
# Helpers
# ---------------------------
def chunked_iterable(iterable: Iterable, size: int):
    it = iter(iterable)
    while True:
        chunk = []
        for _ in range(size):
            try:
                chunk.append(next(it))
            except StopIteration:
                break
        if not chunk:
            break
        yield chunk

    
def get_leo_cdp_database(arango_conn_id: str = "leo_cdp_arangodb"):
    """
    Returns an ArangoDBHook and the connected database handle.

    The function ensures:
    - Safe access to the ArangoDB client.
    - Proper fallback to a default database name.
    - Compatible with Airflow 2.11 provider APIs.
    """
    # Initialize the hook using the Airflow connection ID
    hook = ArangoDBHook(arangodb_conn_id=arango_conn_id)

    # Get the low-level python-arango client
    client = hook.get_conn()  # ensures connection is initialized

    # Determine database name (try connection.extra or fallback)
    db_name = getattr(hook, "database", None) or "leo_cdp_test"

    # Get credentials from the hook (depends on provider’s API)
    username = getattr(hook, "username", None)
    password = getattr(hook, "password", None)

    # Get a database object using the client
    db = client.db(db_name, username=username, password=password)

    return db

def get_pg_dsn():
    """
    Use PostgresHook to derive DSN (URI) that psycopg can consume.
    """
    hook = PostgresHook(postgres_conn_id=PG_CONN_ID)
    # PostgresHook.get_uri() exists and returns a connection URI (postgresql://...)
    try:
        uri = hook.get_uri()
    except Exception:
        # fallback: build from connection
        conn = hook.get_connection(PG_CONN_ID)
        uri = conn.get_uri()
    return uri

# ---------------------------
# Define TypedDicts for data contracts
# ---------------------------

class ProfileRecord(TypedDict):
    cdp_profile_id: str
    tenant_id: str
    full_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    country: Optional[str]
    age: Optional[int]
    gender: Optional[str]
    metadata: str  # JSON string
    profile_embedding: Optional[List[float]]

class TransactionRecord(TypedDict):
    tenant_id: str
    user_id: str
    txn_id: str
    cdp_profile_id: Optional[str]
    source_system: Optional[str]
    txn_type: Optional[str]
    txn_status: Optional[str]
    txn_timestamp: Optional[str] # Arango 'createdAt' is likely an ISO string
    amount: Optional[float]
    currency: Optional[str]
    context_data: str # JSON string
    embedding: Optional[List[float]]
    category_label: Optional[str]
    intent_label: Optional[str]
    intent_confidence: Optional[float]


# ---------------------------
# DAG
# ---------------------------
with DAG(
    dag_id='leo_cdp_to_leo_bot_etl',
    default_args=DEFAULT_ARGS,
    #schedule_interval='@hourly',
    schedule=None,
    start_date=datetime(2025, 1, 1),
    max_active_runs=10,
    catchup=False,
    tags=['leo_cdp', 'etl'],
    params={
        "segment_id": Param("", type="string", description="Segment ID to filter profiles")
    }
) as dag:

    @task()
    def extract_profiles(segment_id: str = "", batch_size: int = 5000) -> List[Dict[str, Any]]:
        """
        Efficiently extracts profiles using key-based pagination and streaming cursor.
        This avoids the performance penalty of OFFSET-based pagination in ArangoDB.

        - Uses `_key` as a stable cursor position.
        - Uses `stream=True` to avoid loading all results at once.
        - Automatically stops when fewer than `batch_size` profiles are fetched.
        """
        if not segment_id:
            log.warning("No segment_id provided, returning empty list.")
            return []

        db = get_leo_cdp_database()

        # AQL query using key-based pagination (faster than LIMIT + OFFSET)
        aql_template = """
        FOR p IN @@col
            FILTER @segment_id IN p.inSegments[*].id 
                AND p.status > 0
                AND (@last_key == "" OR p._key > @last_key)
            SORT p._key ASC
            LIMIT @limit
            RETURN p
        """

        all_profiles = []
        last_key = ""
        total_fetched = 0
        batch_num = 0

        while True:
            bind_vars = {
                "@col": ARANGO_PROFILE_COL,
                "segment_id": segment_id,
                "last_key": last_key,
                "limit": batch_size
            }

            cursor = db.aql.execute(
                aql_template,
                bind_vars=bind_vars,
                batch_size=batch_size,
                stream=True,   # stream results for lower memory footprint
                ttl=600
            )

            batch_profiles = list(cursor)
            fetched = len(batch_profiles)
            if fetched == 0:
                break

            batch_num += 1
            total_fetched += fetched
            all_profiles.extend(batch_profiles)
            last_key = batch_profiles[-1].get("_key", last_key)

            log.info(
                "Batch %d: fetched %d profiles (last_key=%s, total=%d)",
                batch_num, fetched, last_key, total_fetched
            )

            # stop condition
            if fetched < batch_size:
                break

        log.info("Extraction completed. Total profiles fetched: %d", total_fetched)
        return all_profiles

    @task()
    def extract_transactions(profile_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not profile_docs:
            log.warning("No profiles provided, returning empty transaction list")
            return []

        profile_keys = [p["_key"] for p in profile_docs if "_key" in p]
        if not profile_keys:
            log.warning("No valid profile keys found")
            return []

        db = get_leo_cdp_database()

        aql = """
        FOR e IN @@col
            FILTER e._from IN @profile_ids
            RETURN e
        """
        bind_vars = {
            "@col": ARANGO_TXN_COL,
            "profile_ids": [f"cdp_profile/{k}" for k in profile_keys]
        }

        cursor = db.aql.execute(aql, bind_vars=bind_vars)
        txns = list(cursor)
        log.info("Extracted %d transactions related to %d profiles", len(txns), len(profile_keys))
        return txns


    @task()
    def transform_and_embed_profiles(profiles: List[Dict[str, Any]]) -> List[ProfileRecord]:
        """
        Transforms a list of LEO CDP profiles into a format ready for PostgreSQL
        insertion into the `customer_profile` table, including generating embeddings.
        """
        if not profiles:
            return []

        texts = []
        # Store necessary data for final results construction, including extracted SQL fields
        mapping = []

        for p in profiles:
            # 1. Primary Key and Tenant ID
            cdp_id = p.get('_key') or p.get('cdp_profile_id') or p.get('customer_id')
            tenant = p.get('tenant_id') or p.get('tenant') or 'default'

            # 2. Extracted Fields for Direct SQL Columns
            full_name = p.get('firstName', '') + ' ' + p.get('lastName', '') if p.get('firstName') and p.get('lastName') else p.get('full_name')
            
            # Use primary fields from the profile, falling back to empty string if not found
            email = p.get('primaryEmail', '')
            phone = p.get('primaryPhone', '')
            country = p.get('primaryNationality') or p.get('livingCountry', '')
            age = p.get('age') # Can be None
            gender_code = p.get('gender')
            gender = 'Male' if gender_code == 1 else 'Female' if gender_code == 2 else None # Can be None

            # 3. Compose embedding text (using non-empty string fields for rich context)
            text = " ".join(filter(None, [
                str(full_name or ''),
                str(p.get('primaryEmail', '')),
                str(p.get('primaryPhone', '')),
                str(p.get('livingLocation', '')),
                str(p.get('jobTitles', [])),
                str(p.get('dataLabelsAsStr', '')),
                str(p.get('inSegmentsAsStr', '')),
                str(p.get('contentKeywords', [])),
                str(p.get('productKeywords', []))
            ]))

            # Append data needed for the final structured result
            mapping.append((cdp_id, tenant, full_name, email, phone, country, age, gender, p))
            texts.append(text)

        # 4. Generate Embeddings in Batches
        embeddings = []
        if texts:
            for idx_chunk in chunked_iterable(range(len(texts)), EMBED_BATCH_SIZE):
                batch_texts = [texts[i] for i in idx_chunk]
                vecs = get_embeddings_batch(
                    batch_texts
                )
                embeddings.extend(vecs)
        
        # Ensure there are enough embeddings (e.g., if one was too short/empty)
        num_profiles = len(mapping)
        if len(embeddings) != num_profiles:
            # Fallback for error/mismatch: pad with None or a zero vector
            log.warning(f"Embeddings count mismatch ({len(embeddings)} vs {num_profiles}). Padding with None.")
            embeddings.extend([None] * (num_profiles - len(embeddings)))


        # 5. Construct Final Database Records
        results: List[ProfileRecord] = []
        for idx, (cdp_id, tenant, full_name, email, phone, country, age, gender, profile_doc) in enumerate(mapping):
            results.append({
                'cdp_profile_id': cdp_id,
                'tenant_id': tenant,
                'full_name': full_name,
                'email': email,
                'phone': phone,
                'country': country,
                'age': age,
                'gender': gender,
                'metadata': json.dumps(profile_doc, ensure_ascii=False), # Store the original profile JSON
                'profile_embedding': embeddings[idx], # This will be the Python list of floats or None
            })
        return results

    @task()
    def transform_and_embed_txns(txns: List[Dict[str, Any]]) -> List[TransactionRecord]: 
        """
        Transforms a list of ArangoDB transaction events into a format ready for PostgreSQL
        insertion into the `transactional_context` table, including generating embeddings.
        """
        if not txns:
            return []

        texts = []
        mapping = []

        for t in txns:
            # 1. Primary Keys and IDs
            tenant = t.get('tenant_id') or 'default'
            txn_id = t.get('transactionId') or t.get('_key') # Prefer transactionId or fallback to _key
            
            # In ArangoDB edge documents, '_from' is typically the source node (the profile/user)
            user_id = t.get('_from', '').split('/')[-1] if t.get('_from') else None
            cdp_profile_id = user_id # Using the user_id as cdp_profile_id since it comes from the _from field
            
            # 2. Extracted Fields for Direct SQL Columns
            txn_type = t.get('eventMetricId') or 'transaction' # e.g., 'purchase'
            amount = t.get('transactionValue', 0)
            currency = t.get('currencyCode') or 'USD'
            txn_timestamp = t.get('createdAt') or None # Can be None
            
            # 3. Compose textual summary for embedding
            text_parts = [
                txn_type,
                f"Transaction ID {txn_id}",
                f"Amount {amount} {currency}",
            ]
            
            # Add context from relevant ArangoDB fields
            if t.get('assetGroupIds'):
                text_parts.append(f"Asset Groups: {', '.join(t['assetGroupIds'])}")
            if t.get('segmentIds'):
                text_parts.append(f"Segments: {', '.join(t['segmentIds'])}")
            if t.get('totalEvent') is not None and t.get('totalEvent') > 0:
                text_parts.append(f"Total Events: {t['totalEvent']}")
                
            text = " ".join(filter(None, text_parts))
            
            # Store data for final results construction
            mapping.append((tenant, user_id, txn_id, cdp_profile_id, txn_type, amount, currency, txn_timestamp, t))
            texts.append(text)

        # 4. Generate Embeddings in Batches
        embeddings = []
        if texts:
            for idx_chunk in chunked_iterable(range(len(texts)), EMBED_BATCH_SIZE):
                batch_texts = [texts[i] for i in idx_chunk]
                vecs = get_embeddings_batch(
                    batch_texts
                )
                embeddings.extend(vecs)

        num_txns = len(mapping)
        if len(embeddings) != num_txns:
            log.warning(f"Embeddings count mismatch ({len(embeddings)} vs {num_txns}). Padding with None.")
            embeddings.extend([None] * (num_txns - len(embeddings)))

        # 5. Construct Final Database Records
        results: List[TransactionRecord] = []
        for idx, (tenant, user_id, txn_id, cdp_profile_id, txn_type, amount, currency, txn_timestamp, txn_doc) in enumerate(mapping):
            results.append({
                'tenant_id': tenant,
                'user_id': user_id or cdp_profile_id or 'unknown_user', # Ensure user_id is populated
                'txn_id': txn_id or f"autogen_{idx}", # Ensure txn_id is populated
                'cdp_profile_id': cdp_profile_id,
                'source_system': 'ArangoDB',
                'txn_type': txn_type,
                'txn_status': 'completed', # Default
                'txn_timestamp': txn_timestamp,
                'amount': amount,
                'currency': currency,
                'context_data': json.dumps(txn_doc, ensure_ascii=False), # Store the original document
                'embedding': embeddings[idx], # Python list of floats or None
                'category_label': None, # To be determined by another service
                'intent_label': None, # To be determined by another service
                'intent_confidence': 0.0, # Default
            })
        return results

    @task()
    def load_profiles_to_pg(profile_records: List[ProfileRecord]) -> int:
        """
        Loads prepared customer profile records into the PostgreSQL customer_profile table 
        using psycopg's executemany for bulk UPSERT.
        """
        if not profile_records:
            log.info("No profiles to load")
            return 0
        
        dsn = get_pg_dsn()
        upsert_count = 0
        
        # 1. Update SQL to include all customer_profile columns
        upsert_sql = """
            INSERT INTO customer_profile
            (cdp_profile_id, tenant_id, full_name, email, phone, country, age, gender, metadata, profile_embedding, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector, now(), now())
            ON CONFLICT (cdp_profile_id) DO UPDATE
            SET
            tenant_id = EXCLUDED.tenant_id,
            full_name = EXCLUDED.full_name,
            email = EXCLUDED.email,
            phone = EXCLUDED.phone,
            country = EXCLUDED.country,
            age = EXCLUDED.age,
            gender = EXCLUDED.gender,
            metadata = EXCLUDED.metadata,
            profile_embedding = EXCLUDED.profile_embedding,
            updated_at = now();
        """
        
        # 2. Connect and Execute
        try:
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    for chunk in chunked_iterable(profile_records, 200):
                        args = []
                        for r in chunk:
                            # Convert the Python list of floats to a string representation 
                            # (e.g. '[0.1, 0.2]') for the ::vector cast in SQL.
                            embedding_str = str(r['profile_embedding']) if r['profile_embedding'] is not None else None
                            
                            metadata_json_str = r.get('metadata') # .get() is fine here, but 'metadata' is guaranteed
                            
                            # Safeguard: ensure metadata is a JSON string
                            if isinstance(metadata_json_str, dict):
                                metadata_json_str = json.dumps(metadata_json_str, ensure_ascii=False)
                            
                            args.append((
                                r['cdp_profile_id'],
                                r['tenant_id'],
                                r.get('full_name'),
                                r.get('email'),
                                r.get('phone'),
                                r.get('country'),
                                r.get('age'),
                                r.get('gender'),
                                metadata_json_str, # JSON string for jsonb column
                                embedding_str      # String array for vector column
                            ))
                        
                        # Execute bulk insert/update
                        cur.executemany(upsert_sql, args)
                        upsert_count += len(args)
                
                # Commit the transaction
                conn.commit()
                
        except psycopg.Error as e:
            log.error(f"PostgreSQL Error during profile load: {e}")
            # Raise an exception to fail the task
            raise AirflowException(f"Failed to load profiles to Postgres: {e}")
        except Exception as e:
            log.error(f"An unexpected error occurred during profile load: {e}")
            raise AirflowException(f"Unexpected error in load_profiles_to_pg: {e}")


        log.info("Upserted %d profiles to Postgres", upsert_count)
        return upsert_count

    @task()
    def load_txns_to_pg(txn_records: List[TransactionRecord]) -> int: 
        """
        Loads prepared transaction records into the PostgreSQL transactional_context table 
        using psycopg's executemany for bulk UPSERT.
        """
        if not txn_records:
            log.info("No transactions to load")
            return 0
        
        # 1. Prepare DSN and SQL
        dsn = get_pg_dsn()
        upsert_count = 0
        
        upsert_sql = """
            INSERT INTO transactional_context
            (tenant_id, user_id, txn_id, cdp_profile_id, source_system, txn_type, txn_status, txn_timestamp,
            amount, currency, context_data, embedding, category_label, intent_label, intent_confidence, created_at, updated_at, updated_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector,%s,%s,%s, now(), now(), %s)
            ON CONFLICT (tenant_id, user_id, txn_id) DO UPDATE
            SET
                cdp_profile_id = EXCLUDED.cdp_profile_id,
                source_system = EXCLUDED.source_system,
                txn_type = EXCLUDED.txn_type,
                txn_status = EXCLUDED.txn_status,
                txn_timestamp = EXCLUDED.txn_timestamp,
                amount = EXCLUDED.amount,
                currency = EXCLUDED.currency,
                context_data = EXCLUDED.context_data,
                embedding = EXCLUDED.embedding,
                category_label = EXCLUDED.category_label,
                intent_label = EXCLUDED.intent_label,
                intent_confidence = EXCLUDED.intent_confidence,
                updated_at = now(),
                updated_by = EXCLUDED.updated_by;
        """
        
        # 2. Connect and Execute
        try:
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    for chunk in chunked_iterable(txn_records, 200):
                        args = []
                        for r in chunk:
                            
                            # Convert list to string for ::vector cast
                            embedding_str = str(r['embedding']) if r['embedding'] is not None else None
                            
                            args.append((
                                # FIX 2: Use direct access r[] instead of r.get()
                                # for keys guaranteed by the TypedDict
                                r['tenant_id'],
                                r['user_id'],                               
                                r['txn_id'],
                                r.get('cdp_profile_id'),
                                r.get('source_system'),
                                r['txn_type'],
                                r.get('txn_status', 'completed'), 
                                r.get('txn_timestamp'),
                                r.get('amount', 0.0),
                                r.get('currency', 'USD'),
                                r['context_data'], # Already a JSON string
                                embedding_str, 
                                r.get('category_label'),
                                r.get('intent_label'),
                                r.get('intent_confidence', 0.0),
                                DATA_SOURCE_TAG # Use constant
                            ))
                        
                        # Execute bulk insert/update
                        cur.executemany(upsert_sql, args)
                        upsert_count += len(args)
                
                # Commit the transaction
                conn.commit()
                
        except psycopg.Error as e:
            log.error(f"PostgreSQL Error during transaction load: {e}")
            # Raise an exception to fail the task
            raise AirflowException(f"Failed to load transactions to Postgres: {e}")
        except Exception as e:
            log.error(f"An unexpected error occurred during transaction load: {e}")
            raise AirflowException(f"Unexpected error in load_txns_to_pg: {e}")


        log.info("Upserted %d transactions to Postgres", upsert_count)
        return upsert_count

    @task()
    # FIX 3: Update signature to match input type from upstream task
    def collect_tenants_from_profiles(profiles: List[ProfileRecord]):
        if not profiles:
            return []
        tenants = list({p['tenant_id'] for p in profiles if p.get('tenant_id')})
        log.info("Found %d unique tenants to refresh", len(tenants))
        return tenants

    @task()
    def refresh_metrics_task(tenants: List[str]):
        if not tenants:
            log.info("No tenants to refresh")
            return 0
        dsn = get_pg_dsn()
        try:
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    for t in tenants:
                        log.info("Refreshing metrics for tenant: %s", t)
                        cur.execute("SELECT refresh_customer_metrics(%s);", (t,))
                conn.commit()
        except psycopg.Error as e:
            log.error(f"Failed to refresh metrics for tenants: {tenants}. Error: {e}")
            raise AirflowException(f"Failed to refresh metrics: {e}")
            
        return len(tenants)

    # ---------------------------
    # DAG execution graph
    # ---------------------------   
    
    extracted_profiles = extract_profiles("{{ params.segment_id }}")
    extracted_txns = extract_transactions(extracted_profiles)
    
    transformed_profiles = transform_and_embed_profiles(extracted_profiles)
    transformed_txns = transform_and_embed_txns(extracted_txns)
    
    upsert_profiles = load_profiles_to_pg(transformed_profiles)
    upsert_txns = load_txns_to_pg(transformed_txns)
    
    tenants_list = collect_tenants_from_profiles(transformed_profiles)
    
    refresh = refresh_metrics_task(tenants_list)
    refresh.set_upstream([upsert_profiles, upsert_txns])