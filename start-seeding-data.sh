#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
ENV_FILE="$PROJECT_ROOT/.env"
SEED_FILE="$PROJECT_ROOT/sql_scripts/sample_places.sql"
PG_CONTAINER_NAME="${PG_CONTAINER_NAME:-pgsql18_vector}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  echo "❌ Environment file not found: $ENV_FILE" >&2
  exit 1
fi
DATABASE_NAME="${PGSQL_DB_NAME:-leo360}"

if [[ ! -f "$SEED_FILE" ]]; then
  echo "❌ Seed SQL file not found: $SEED_FILE" >&2
  exit 1
fi

DATABASE_URL="${PGSQL_DB_URL:-}"
if [[ -z "$DATABASE_URL" ]]; then
  echo "❌ PGSQL_DB_URL must be configured in $ENV_FILE" >&2
  exit 1
fi

USE_HOST_PSQL=false
if command -v psql >/dev/null 2>&1 \
  && psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -Atc "SELECT 1" >/dev/null 2>&1; then
  USE_HOST_PSQL=true
elif command -v docker >/dev/null 2>&1 \
  && docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER_NAME"; then
  :
else
  echo "❌ Neither a usable psql client nor a running PostgreSQL Docker container was found." >&2
  exit 1
fi

run_query() {
  if [[ "$USE_HOST_PSQL" == true ]]; then
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 "$@"
  else
    docker exec -i -u postgres "$PG_CONTAINER_NAME" \
      psql -v ON_ERROR_STOP=1 -d "$DATABASE_NAME" "$@"
  fi
}

apply_sql_file() {
  local sql_file=$1
  if [[ "$USE_HOST_PSQL" == true ]]; then
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$sql_file"
  else
    docker exec -i -u postgres "$PG_CONTAINER_NAME" \
      psql -v ON_ERROR_STOP=1 -d "$DATABASE_NAME" < "$sql_file"
  fi
}

ACTUAL_DATABASE="$(run_query -Atc "SELECT current_database();")"
if [[ "$ACTUAL_DATABASE" != "$DATABASE_NAME" ]]; then
  echo "❌ Connected to database '$ACTUAL_DATABASE'; expected '$DATABASE_NAME'." >&2
  exit 1
fi
echo "✅ Connected to database '$DATABASE_NAME'."

if [[ "$(run_query -Atc "SELECT to_regclass('public.places');")" != "places" ]]; then
  echo "⚙️  Table public.places is missing. Applying the canonical schema..."
  apply_sql_file "$PROJECT_ROOT/sql_scripts/leo360_schema.sql"
fi

if [[ "$(run_query -Atc "SELECT to_regclass('public.places');")" != "places" ]]; then
  echo "❌ Canonical schema did not create public.places." >&2
  exit 1
fi

echo "🌱 Seeding places from $SEED_FILE..."
apply_sql_file "$SEED_FILE"
echo "✅ Seed data applied successfully."