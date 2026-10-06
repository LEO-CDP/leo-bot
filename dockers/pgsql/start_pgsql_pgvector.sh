#!/bin/bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

# --- Docker configs ---
POSTGRES_VERSION=18
POSTGRES_IMAGE="postgis/postgis:18-3.6"
CONTAINER_NAME="pgsql${POSTGRES_VERSION}_vector"
VLAN_NAME="leo-vlan"
DATA_VOLUME="pgdata_vector${POSTGRES_VERSION}"
LEGACY_CONTAINER_NAME="pgsql16_vector"
LEGACY_DATA_VOLUME="pgdata_vector"

# --- POSTGRES config ---
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="password"
DEFAULT_DB="postgres"
TARGET_DB="leo360"
KEYCLOAK_DB="keycloak"
HOST_PORT="${PGSQL_DB_PORT:-5433}"

# --- SQL schema config ---
SCHEMA_VERSION=251203
SCHEMA_DESCRIPTION="init database schema leo360 for leo bot in CDP and chatbot for end user"
SQL_FILE_PATH="$PROJECT_ROOT/sql_scripts/leo360_schema.sql"

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

if ! docker ps -a --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}$"; then
  echo "📥 Pulling PostgreSQL image '${POSTGRES_IMAGE}'..."
  docker pull "$POSTGRES_IMAGE" || { echo "❌ Failed to pull PostgreSQL ${POSTGRES_VERSION} image."; exit 1; }
fi

# PostgreSQL major versions use incompatible data directories. Remove the
# previous PG16 container and volume only when the destructive reset is explicit.
if docker ps -a --format '{{.Names}}' | grep -Eq "^${LEGACY_CONTAINER_NAME}$" \
    || docker volume inspect "$LEGACY_DATA_VOLUME" >/dev/null 2>&1; then
  if [ "$RESET_DB" != true ]; then
    echo "❌ PostgreSQL 16 data was found. Re-run with --reset-db to delete it and initialize PostgreSQL ${POSTGRES_VERSION}."
    exit 1
  fi

  if docker ps -a --format '{{.Names}}' | grep -Eq "^${LEGACY_CONTAINER_NAME}$"; then
    echo "🗑️ Removing legacy PostgreSQL container '${LEGACY_CONTAINER_NAME}'..."
    docker rm -f "$LEGACY_CONTAINER_NAME" || { echo "❌ Failed to remove legacy container."; exit 1; }
  fi
  if docker volume inspect "$LEGACY_DATA_VOLUME" >/dev/null 2>&1; then
    echo "🗑️ Removing legacy PostgreSQL volume '${LEGACY_DATA_VOLUME}'..."
    docker volume rm "$LEGACY_DATA_VOLUME" || { echo "❌ Failed to remove legacy volume."; exit 1; }
  fi
fi

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
    -v "$DATA_VOLUME:/var/lib/postgresql" \
    "$POSTGRES_IMAGE" || { echo "❌ Failed to launch PostgreSQL ${POSTGRES_VERSION} container."; exit 1; }


  wait_for_postgres

fi

# --- Ensure pgvector is installed in existing and new containers ---
if ! docker exec "$CONTAINER_NAME" test -f "/usr/share/postgresql/${POSTGRES_VERSION}/extension/vector.control"; then
  echo "📦 Installing pgvector extension..."
  if ! docker exec -u root "$CONTAINER_NAME" bash -ec "apt-get update && apt-get install -y postgresql-${POSTGRES_VERSION}-pgvector"; then
    echo "❌ Failed to install the PostgreSQL ${POSTGRES_VERSION} pgvector package."
    exit 1
  fi
fi

if ! docker exec "$CONTAINER_NAME" test -f "/usr/share/postgresql/${POSTGRES_VERSION}/extension/vector.control"; then
  echo "❌ pgvector installation did not provide vector.control for PostgreSQL ${POSTGRES_VERSION}."
  exit 1
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
if ! DB_EXISTS=$(docker exec -u postgres "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -d "$DEFAULT_DB" -tc "SELECT 1 FROM pg_database WHERE datname='${TARGET_DB}';"); then
  echo "❌ Failed to check whether database '${TARGET_DB}' exists."
  exit 1
fi
DB_EXISTS="$(printf '%s' "$DB_EXISTS" | tr -d '[:space:]')"
if [ "$DB_EXISTS" != "1" ]; then
  echo "🚀 Creating database '${TARGET_DB}'..."
  docker exec -u postgres "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -d "$DEFAULT_DB" -c "CREATE DATABASE ${TARGET_DB};" || { echo "❌ Failed to create database '${TARGET_DB}'."; exit 1; }
fi

echo "🔄 Checking if database '${KEYCLOAK_DB}' exists..."
if ! KEYCLOAK_DB_EXISTS=$(docker exec -u postgres "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -d "$DEFAULT_DB" -tc "SELECT 1 FROM pg_database WHERE datname='${KEYCLOAK_DB}';"); then
  echo "❌ Failed to check whether database '${KEYCLOAK_DB}' exists."
  exit 1
fi
KEYCLOAK_DB_EXISTS="$(printf '%s' "$KEYCLOAK_DB_EXISTS" | tr -d '[:space:]')"
if [ "$KEYCLOAK_DB_EXISTS" != "1" ]; then
  echo "🚀 Creating database '${KEYCLOAK_DB}'..."
  docker exec -u postgres "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -d "$DEFAULT_DB" -c "CREATE DATABASE ${KEYCLOAK_DB};" || {
    echo "❌ Failed to create database '${KEYCLOAK_DB}'."
    exit 1
  }
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

# --- Ensure touchpoint schema and 768-dimensional embeddings ---
echo "🔧 Ensuring touchpoint schema..."
docker exec -u postgres "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -d "$TARGET_DB" -c "
CREATE TABLE IF NOT EXISTS touchpoints (
    touchpoint_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(50) NOT NULL DEFAULT 'default',
    latitude DECIMAL(9, 6) NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude DECIMAL(9, 6) NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    geom GEOMETRY(Point, 4326) NOT NULL,
    name TEXT,
    description TEXT,
    type VARCHAR(50),
    keywords TEXT[],
    embedding VECTOR(768),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE touchpoints ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE touchpoints ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE touchpoints ADD COLUMN IF NOT EXISTS type VARCHAR(50);
ALTER TABLE touchpoints ADD COLUMN IF NOT EXISTS keywords TEXT[];
ALTER TABLE touchpoints ADD COLUMN IF NOT EXISTS embedding VECTOR(768);
DROP INDEX IF EXISTS idx_touchpoints_embedding;
DO \$\$
DECLARE
    embedding_type TEXT;
BEGIN
    SELECT format_type(a.atttypid, a.atttypmod)
    INTO embedding_type
    FROM pg_attribute AS a
    JOIN pg_class AS c ON c.oid = a.attrelid
    WHERE c.relname = 'touchpoints'
      AND a.attname = 'embedding'
      AND NOT a.attisdropped;

    IF embedding_type = 'vector(384)' THEN
        ALTER TABLE touchpoints
        ALTER COLUMN embedding TYPE VECTOR(768)
        USING NULL;
    END IF;
END\$\$;
CREATE INDEX IF NOT EXISTS idx_touchpoints_geom ON touchpoints USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_touchpoints_geog
    ON touchpoints USING GIST ((geom::geography));
CREATE INDEX IF NOT EXISTS idx_touchpoints_user ON touchpoints (user_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_touchpoints_embedding
    ON touchpoints USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;
" || { echo "❌ Failed to prepare touchpoint schema."; exit 1; }

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

  docker exec -i -u postgres "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -d "$TARGET_DB" < "$sql_file_path" || { echo "❌ Failed to apply migration $version"; exit 1; }

  docker exec -u postgres "$CONTAINER_NAME" psql -d "$TARGET_DB" -c \
    "INSERT INTO schema_migrations (version, description, applied_at) VALUES ($version, '$description', NOW());" || { echo "❌ Failed to record migration $version"; exit 1; }

  echo "✅ Migration $version applied successfully."
}

# --- Apply initial schema migration if needed ---
if [ $CURRENT_VERSION -lt $SCHEMA_VERSION ]; then
  apply_migration $SCHEMA_VERSION "$SCHEMA_DESCRIPTION" "$SQL_FILE_PATH"
fi

# --- Verify all tables exist ---
TABLES=("chat_messages" "chat_message_embeddings" "places" "touchpoints" "schema_migrations" "system_users" "conversational_context" "knowledge_sources" "knowledge_chunks" "customer_profile" "transactional_context" "customer_metrics" "tenant_metrics_config")
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

SERVER_VERSION=$(docker exec -u postgres "$CONTAINER_NAME" psql -d "$DEFAULT_DB" -t -c "SHOW server_version;" | tr -d '[:space:]')
echo "✅ PostgreSQL ${SERVER_VERSION} + PostGIS + pgvector is ready."
echo "   ➜ DB: $TARGET_DB"
echo "   ➜ Tables: ${TABLES[*]}"
echo "   ➜ Extensions: vector, postgis"
echo "   ➜ Schema Version: $SCHEMA_VERSION"
echo "   ➜ Port: $HOST_PORT"
