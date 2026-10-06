#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${KEYCLOAK_CONTAINER_NAME:-keycloak}"

if ! docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  echo "ℹ️  Keycloak container '$CONTAINER_NAME' does not exist."
  exit 0
fi

if docker ps --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  echo "🛑 Stopping Keycloak container '$CONTAINER_NAME'..."
  docker stop "$CONTAINER_NAME" >/dev/null
  echo "✅ Keycloak stopped."
else
  echo "ℹ️  Keycloak container '$CONTAINER_NAME' is already stopped."
fi
