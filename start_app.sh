#!/bin/bash
set -euo pipefail

APP_NAME="leobot"
APP_MODULE="main_app:leobot"
DIR_PATH="/build/leo-bot"
VENV_PATH="$DIR_PATH/env"
HOST="0.0.0.0"
PORT="8888"

# Logs go into /build/leo-bot/logs
LOG_DIR="$DIR_PATH/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${APP_NAME}-$(date '+%Y-%m-%d_%H-%M-%S').log"

cd "$DIR_PATH" || { echo "❌ Directory not found: $DIR_PATH"; exit 1; }

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
if [[ -f "$VENV_PATH/bin/activate" ]]; then
  source "$VENV_PATH/bin/activate"
else
  echo "❌ Virtual environment not found at $VENV_PATH"
  exit 1
fi

# Start PGSQL instance
bash ./dockers/pgsql/start_pgsql_pgvector.sh

# Start new instance
echo "🚀 Starting $APP_NAME on port $PORT..."

nohup uvicorn "$APP_MODULE" \
  --reload \
  --env-file .env \
  --host "$HOST" \
  --port "$PORT" \
  >> "$LOG_FILE" 2>&1 &

NEW_PID=$!
echo "✅ Started $APP_NAME (PID: $NEW_PID). Logging to $LOG_FILE"

deactivate
