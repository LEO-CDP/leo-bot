#!/bin/bash
set -euo pipefail

APP_NAME="leobot"
APP_MODULE="main_app:leobot"
DIR_PATH="/build/leo-bot"
VENV_PATH="$DIR_PATH/env"
HOST="0.0.0.0"
PORT="8888"
WORKERS="${UVICORN_WORKERS:-1}"
SEED_DATA=false
RESET_DB=false

for arg in "$@"; do
  case "$arg" in
    --seed-data)
      SEED_DATA=true
      ;;
    --reset-db)
      RESET_DB=true
      ;;
    *)
      echo "❌ Unknown option: $arg"
      exit 1
      ;;
  esac
done

# Logs go into /build/leo-bot/logs
LOG_DIR="$DIR_PATH/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${APP_NAME}-$(date '+%Y-%m-%d_%H-%M-%S').log"

cd "$DIR_PATH" || { echo "❌ Directory not found: $DIR_PATH"; exit 1; }

ENV_FILE="${LEO_ENV_FILE:-$DIR_PATH/.env}"
if [[ -f "$ENV_FILE" ]]; then
  echo "📄 Loading configuration from $ENV_FILE..."
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  echo "⚠️  Environment file not found at $ENV_FILE. Using exported environment variables."
fi
WORKERS="${UVICORN_WORKERS:-$WORKERS}"

# Clean old logs (older than 2 days)
echo "🧹 Cleaning logs older than 2 days in $LOG_DIR..."
find "$LOG_DIR" -type f -name "*.log" -mtime +2 -exec rm -f {} \;

# Find and stop any running instance
PIDS=$(pgrep -f "uvicorn.*${APP_MODULE}" || true)
if [[ -n "$PIDS" ]]; then
  echo "🛑 Stopping existing $APP_NAME process(es): $PIDS"
  kill -15 $PIDS
  # Wait up to 7 seconds for graceful exit
  for i in {1..7}; do
    sleep 1
    if ! pgrep -f "uvicorn.*${APP_MODULE}" >/dev/null; then
      break
    fi
  done
  # Force kill if still running
  if pgrep -f "uvicorn.*${APP_MODULE}" >/dev/null; then
    echo "⚠️  Forcing termination of lingering processes."
    pkill -9 -f "uvicorn.*${APP_MODULE}" || true
  fi
else
  echo "ℹ️  No running $APP_NAME instance found."
fi

# Activate virtual environment
if [[ ! -x "$VENV_PATH/bin/python" ]]; then
  echo "🐍 Virtual environment not found. Creating Python 3.12 environment at $VENV_PATH..."
  if ! command -v python3.12 >/dev/null 2>&1; then
    echo "❌ Python 3.12 is required but python3.12 was not found."
    exit 1
  fi
  python3.12 -m venv "$VENV_PATH"
  "$VENV_PATH/bin/python" -m pip install --upgrade pip
  "$VENV_PATH/bin/python" -m pip install -r "$DIR_PATH/requirements.txt"
elif [[ ! -f "$VENV_PATH/bin/activate" ]]; then
  echo "❌ Virtual environment is incomplete at $VENV_PATH"
  exit 1
fi

source "$VENV_PATH/bin/activate"

PYTHON_MINOR="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$PYTHON_MINOR" != "3.12" ]]; then
  echo "❌ Python 3.12 is required, but the active environment uses Python ${PYTHON_MINOR}."
  exit 1
fi
echo "✅ Using Python ${PYTHON_MINOR}."

# Start PGSQL instance
PGSQL_ARGS=()
if [[ "$RESET_DB" == true ]]; then
  echo "⚠️  --reset-db enabled. Existing PostgreSQL 16 data will be deleted."
  PGSQL_ARGS+=(--reset-db)
fi
bash ./dockers/pgsql/start_pgsql_pgvector.sh "${PGSQL_ARGS[@]}"

if [[ "$SEED_DATA" == true ]]; then
  echo "🌱 --seed-data enabled. Loading sample places..."
  bash ./start-seeding-data.sh
fi

# Start new instance
echo "🚀 Starting $APP_NAME on port $PORT..."

UVICORN_ARGS=(
  "$APP_MODULE"
  --host "$HOST"
  --port "$PORT"
  --workers "$WORKERS"
)
if [[ -f "$ENV_FILE" ]]; then
  UVICORN_ARGS+=(--env-file "$ENV_FILE")
fi

nohup uvicorn "${UVICORN_ARGS[@]}" \
  >> "$LOG_FILE" 2>&1 &

NEW_PID=$!
echo "✅ Started $APP_NAME (PID: $NEW_PID). Logging to $LOG_FILE"

deactivate
