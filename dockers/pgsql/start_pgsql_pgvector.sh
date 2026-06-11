#!/bin/bash

# --- Docker configs ---
CONTAINER_NAME="pgsql16_vector"
VLAN_NAME="leo-vlan"
DATA_VOLUME="pgdata_vector"

# --- POSTGRES config ---
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="password"
DEFAULT_DB="postgres"
TARGET_DB="customer360"
HOST_PORT=5432

# --- SQL schema config ---
SCHEMA_VERSION=251203
SCHEMA_DESCRIPTION="init database schema customer360 for leo bot in CDP and chatbot for end user"
SQL_FILE_PATH="./sql_scripts/customer360_schema.sql"

# --- Parse options ---
RESET_DB=false
for arg in "$@"; do
  case $arg in
    --reset-db)
      RESET_DB=true
      shift
      ;;
  esac
done

# --- Function to check PostgreSQL readiness ---
wait_for_postgres() {
  local max_attempts=10
  local attempt=1
  echo "⏳ Checking if PostgreSQL is ready..."
  until docker exec -u postgres $CONTAINER_NAME psql -d $DEFAULT_DB -c "SELECT 1;" >/dev/null 2>&1; do
    if [ $attempt -ge $max_attempts ]; then
      echo "❌ Error: PostgreSQL is not ready after $max_attempts attempts."
      exit 1
    fi
    echo "⏳ Attempt $attempt/$max_attempts: Waiting for PostgreSQL..."
    sleep 2
    ((attempt++))
  done
  echo "🟢 PostgreSQL is ready."
}

# --- Check if container exists ---
if docker ps -a --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}$"; then
  # If exists but not running, start it
  if ! docker ps --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}$"; then
    echo "🔄 Starting existing container '${CONTAINER_NAME}'..."
    docker start "$CONTAINER_NAME"
    wait_for_postgres
  else
    echo "🟢 PostgreSQL container '${CONTAINER_NAME}' is already running."
    wait_for_postgres
  fi
else
  # Create volume if needed
  if ! docker volume ls | grep -q "$DATA_VOLUME"; then
    docker volume create "$DATA_VOLUME"
  fi

  # docker network ls | grep leo-vlan || docker network create leo-vlan

  echo "🚀 Launching new PostgreSQL container '${CONTAINER_NAME}'..."
  docker run -d \
    --name "$CONTAINER_NAME" \
    --network "$VLAN_NAME" \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$DEFAULT_DB" \
    -p "$HOST_PORT:5432" \
    -v "$DATA_VOLUME:/var/lib/postgresql/data" \
    postgis/postgis:16-3.5


  wait_for_postgres

  # Install pgvector inside the container
  echo "📦 Installing pgvector extension..."
  docker exec -u root $CONTAINER_NAME bash -c "apt-get update && apt-get install -y postgresql-16-pgvector"
fi

# --- Fix collation version mismatch ---
echo "🔧 Checking and fixing collation version mismatch for 'postgres' and 'template1'..."
docker exec -u postgres $CONTAINER_NAME psql -d $DEFAULT_DB -c "ALTER DATABASE postgres REFRESH COLLATION VERSION;" || echo "⚠️ Warning: Failed to refresh 'postgres'."
docker exec -u postgres $CONTAINER_NAME psql -d template1 -c "ALTER DATABASE template1 REFRESH COLLATION VERSION;" || echo "⚠️ Warning: Failed to refresh 'template1'."

# --- Drop DB if requested ---
if [ "$RESET_DB" = true ]; then
  echo "⚠️ --reset-db detected. Dropping database '${TARGET_DB}' if exists..."
  docker exec -u postgres $CONTAINER_NAME psql -d $DEFAULT_DB -c "DROP DATABASE IF EXISTS ${TARGET_DB};"
fi

# --- Create DB if not exists ---
echo "🔄 Checking if database '${TARGET_DB}' exists..."
DB_EXISTS=$(docker exec -u postgres $CONTAINER_NAME psql -d $DEFAULT_DB -tc "SELECT 1 FROM pg_database WHERE datname='${TARGET_DB}';" | tr -d '[:space:]')
if [ "$DB_EXISTS" != "1" ]; then
  echo "🚀 Creating database '${TARGET_DB}'..."
  docker exec -u postgres $CONTAINER_NAME psql -d $DEFAULT_DB -c "CREATE DATABASE ${TARGET_DB};"
fi

# --- Ensure connection to target database ---
wait_for_postgres_target() {
  local max_attempts=5
  local attempt=1
  echo "⏳ Checking if database '${TARGET_DB}' is accessible..."
  until docker exec -u postgres $CONTAINER_NAME psql -d $TARGET_DB -c "SELECT 1;" >/dev/null 2>&1; do
    if [ $attempt -ge $max_attempts ]; then
      echo "❌ Error: Database '${TARGET_DB}' is not accessible after $max_attempts attempts."
      exit 1
    fi
    echo "⏳ Attempt $attempt/$max_attempts: Waiting for database '${TARGET_DB}'..."
    sleep 2
    ((attempt++))
  done
  echo "🟢 Database '${TARGET_DB}' is accessible."
}
wait_for_postgres_target

# --- Enable extensions ---
echo "🔧 Enabling extensions in '${TARGET_DB}'..."
docker exec -u postgres $CONTAINER_NAME psql -d $TARGET_DB -c "CREATE EXTENSION IF NOT EXISTS vector;" || { echo "❌ Failed to enable 'vector'"; exit 1; }
docker exec -u postgres $CONTAINER_NAME psql -d $TARGET_DB -c "CREATE EXTENSION IF NOT EXISTS postgis;" || { echo "❌ Failed to enable 'postgis'"; exit 1; }

# --- Create schema_migrations table ---
echo "🔧 Creating schema_migrations table..."
docker exec -u postgres $CONTAINER_NAME psql -d $TARGET_DB -c "
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT NOW(),
    description TEXT
);
"

# --- Check current schema version ---
echo "🔍 Checking current schema version..."
CURRENT_VERSION=$(docker exec -u postgres $CONTAINER_NAME psql -d $TARGET_DB -t -c "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1;" 2>/dev/null | tr -d '[:space:]' || echo "0")
if [ -z "$CURRENT_VERSION" ]; then CURRENT_VERSION=0; fi
echo "ℹ️ Current schema version: $CURRENT_VERSION"

# --- Function to apply migration ---
apply_migration() {
  local version=$1
  local description=$2
  local sql_file_path=$3

  echo "🚀 Applying migration for version $version: $description"

  if [[ ! -f "$sql_file_path" ]]; then
    echo "❌ SQL file not found: $sql_file_path"
    exit 1
  fi

  docker exec -i -u postgres "$CONTAINER_NAME" psql -d "$TARGET_DB" < "$sql_file_path" || { echo "❌ Failed to apply migration $version"; exit 1; }

  docker exec -u postgres "$CONTAINER_NAME" psql -d "$TARGET_DB" -c \
    "INSERT INTO schema_migrations (version, description, applied_at) VALUES ($version, '$description', NOW());" || { echo "❌ Failed to record migration $version"; exit 1; }

  echo "✅ Migration $version applied successfully."
}

# --- Apply initial schema migration if needed ---
if [ $CURRENT_VERSION -lt $SCHEMA_VERSION ]; then
  apply_migration $SCHEMA_VERSION "$SCHEMA_DESCRIPTION" "$SQL_FILE_PATH"
fi

# --- Verify all tables exist ---
TABLES=("chat_messages" "chat_message_embeddings" "places" "schema_migrations" "system_users" "conversational_context" "knowledge_sources" "knowledge_chunks" "customer_profile" "transactional_context" "customer_metrics" "tenant_metrics_config")
for table in "${TABLES[@]}"; do
  docker exec -u postgres $CONTAINER_NAME psql -d $TARGET_DB -tc "SELECT 1 FROM pg_tables WHERE tablename = '$table'" | grep -q 1 || { echo "❌ Table '$table' missing"; exit 1; }
done

# --- Setting restart policy
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Setting restart policy for: $CONTAINER_NAME"
  docker update --restart=unless-stopped "$CONTAINER_NAME"
  echo "Done."
else
  echo "Container '$CONTAINER_NAME' not found."
  exit 1
fi

echo "✅ PostgreSQL 16 + PostGIS + pgvector is ready."
echo "   ➜ DB: $TARGET_DB"
echo "   ➜ Tables: ${TABLES[*]}"
echo "   ➜ Extensions: vector, postgis"
echo "   ➜ Schema Version: $SCHEMA_VERSION"
echo "   ➜ Port: $HOST_PORT"
