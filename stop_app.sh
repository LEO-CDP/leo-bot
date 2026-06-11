#!/bin/sh

# kill running uvicorn process
PID=$(pgrep -f "uvicorn main_app:leobot")

if [ -n "$PID" ]; then
  echo "Stopping existing uvicorn process: $PID"
  kill -15 "$PID"
  sleep 2
else
  echo "No uvicorn process found"
fi

# remove old log files in current folder
echo "Cleaning old log files..."
find . -maxdepth 1 -type f -name "*.log" -exec rm -f {} \;

echo "Done."
