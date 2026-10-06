#!/bin/bash
set -e

# ==========================================
# 🔧 CONFIGURATION
# ==========================================

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$SCRIPT_DIR/keycloak.env"
CONTAINER_NAME="keycloak"
VLAN_NAME="leo-vlan"
VOLUME_NAME="keycloak_data"

# Load environment variables
if [ -f "$ENV_FILE" ]; then
  echo -e "\e[36m📄 Loading environment from $ENV_FILE\e[0m"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  echo -e "\e[33m⚠️  No keycloak.env file found — using default values\e[0m"
fi

# ==========================================
# 🧭 OPTIONS
# ==========================================

RESET_DATA=false
if [[ "$1" == "--reset" ]]; then
  RESET_DATA=true
  echo -e "\e[31m⚠️  Reset mode enabled: old data will be DELETED!\e[0m"
fi

# ==========================================
# 🔍 CHECK EXISTING CONTAINER
# ==========================================

DESIRED_DB_URL="jdbc:postgresql://${PG_HOST:-pgsql18_vector}:${PG_PORT:-5432}/${PG_DATABASE:-keycloak}"
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  if [ "$RESET_DATA" = true ]; then
    echo -e "\n\e[33m🧹 Removing existing container and volume...\e[0m"
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker volume rm "$VOLUME_NAME" >/dev/null 2>&1 || true
  else
    CURRENT_DB_URL="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER_NAME" \
      | sed -n 's/^KC_DB_URL=//p')"
    if [[ "$CURRENT_DB_URL" == "$DESIRED_DB_URL" ]]; then
      echo -e "\n\e[34m🔁 Restarting existing Keycloak container...\e[0m"
      docker restart "$CONTAINER_NAME"
      echo -e "\e[32m✅ Keycloak restarted successfully!\e[0m"
      docker ps | grep "$CONTAINER_NAME"
      exit 0
    fi

    echo -e "\n\e[33m🔄 Recreating Keycloak container with shared PostgreSQL configuration...\e[0m"
    docker rm -f "$CONTAINER_NAME" >/dev/null
  fi
else
  echo -e "\n\e[34m🚀 No existing container found, starting new one...\e[0m"
fi

# ==========================================
# 🧱 CREATE VOLUME
# ==========================================

if ! docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  echo -e "\e[36m📦 Creating Docker volume for Keycloak data: $VOLUME_NAME\e[0m"
  docker volume create "$VOLUME_NAME" >/dev/null
fi

# ==========================================
# 🚀 STARTUP
# ==========================================

echo -e "\n\e[32m🚀 Starting Keycloak ${KEYCLOAK_VERSION:-26.4.2} on port ${KEYCLOAK_PORT:-8080} ...\e[0m"

docker run -d \
  --name "$CONTAINER_NAME" \
  --network $VLAN_NAME \
  --add-host=host.docker.internal:host-gateway \
  -p ${KEYCLOAK_PORT:-8080}:8080 \
  -e TZ=Asia/Ho_Chi_Minh \
  -v /etc/localtime:/etc/localtime:ro \
  -v /etc/timezone:/etc/timezone:ro \
  -v "$PROJECT_ROOT/dockers/keycloak/themes/leobot:/opt/keycloak/themes/leobot" \
  -v "$VOLUME_NAME":/opt/keycloak/data \
  \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=${KC_BOOTSTRAP_ADMIN_USERNAME:-admin} \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=${KC_BOOTSTRAP_ADMIN_PASSWORD:-admin} \
  \
  -e KC_PROXY=${KC_PROXY:-edge} \
  -e KC_PROXY_HEADERS=${KC_PROXY_HEADERS:-xforwarded} \
  -e KC_HOSTNAME_STRICT=${KC_HOSTNAME_STRICT:-false} \
  -e KC_HOSTNAME_STRICT_HTTPS=${KC_HOSTNAME_STRICT_HTTPS:-true} \
  -e KC_HTTP_ENABLED=${KC_HTTP_ENABLED:-true} \
  -e KC_HTTP_RELATIVE_PATH=${KC_HTTP_RELATIVE_PATH:-/} \
  -e KC_HOSTNAME_URL=${KC_HOSTNAME_URL:-https://leoid.example.com} \
  \
  -e KC_DB=postgres \
  -e KC_DB_URL="jdbc:postgresql://${PG_HOST:-pgsql18_vector}:${PG_PORT:-5432}/${PG_DATABASE:-keycloak}" \
  -e KC_DB_USERNAME=${PG_USERNAME:-postgres} \
  -e KC_DB_PASSWORD=${PG_PASSWORD:-password} \
  \
  quay.io/keycloak/keycloak:${KEYCLOAK_VERSION:-26.4.2} \
  start

# ==========================================
# 📊 LOGGING
# ==========================================

echo -e "\n\e[36m📜 Docker container started successfully!\e[0m"
echo -e "\e[32m🌐 Access Keycloak at: ${KC_HOSTNAME_URL:-https://leoid.example.com}\e[0m"
echo -e "\e[36m🪵 Showing live logs (Ctrl+C to exit)\e[0m\n"

sleep 3

# --- Setting restart policy
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Setting restart policy for: $CONTAINER_NAME"
  docker update --restart=unless-stopped "$CONTAINER_NAME"
  echo "Done."
else
  echo "Container '$CONTAINER_NAME' not found."
  exit 1
fi

# wait to show logs
sleep 1
docker logs -f "$CONTAINER_NAME"