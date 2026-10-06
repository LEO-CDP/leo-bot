# 🦾 Keycloak Docker Launcher

This repository provides a **simple, configurable shell script** (`run-keycloak.sh`) for running **Keycloak** in Docker — complete with HTTPS reverse-proxy support (e.g. via Nginx).
It’s designed for **local or staging setups** where you want **Keycloak reachable over HTTPS** (like `https://leoid.example.com`) without managing its own TLS certificates.

---

## 🚀 Features

* **Smart restart** — if Keycloak is already running, it just restarts it
* **Optional reset mode** (`--reset`) — removes old container **and deletes all data**
* **Persistent data** — uses a Docker volume (`keycloak_data`) to retain users/realms
* **Loads environment variables** from `.env`
* **Colorized terminal output** for easy reading
* **Auto-tail logs** for quick feedback after startup
* Works seamlessly with **Nginx reverse proxy + HTTPS termination**
* Clean and extensible — ready to integrate PostgreSQL or Docker Compose later

---

## ⚙️ Requirements

* **Docker** installed and running
* **Nginx** (or another reverse proxy) handling HTTPS on port 443
* A hostname (e.g. `leoid.example.com`) mapped to `127.0.0.1` in `/etc/hosts`
* Linux or macOS shell (tested on Ubuntu and Fedora)

---

## 📁 Project structure

```
keycloak/
│
├── run-keycloak.sh      # Main launcher script
├── .env                 # Configuration (environment variables)
└── README.md            # You are here
```

---

## 🔧 Setup

### 1. Clone this repo or copy the files

```bash
mkdir ~/keycloak && cd ~/keycloak
```

---

### 2. Create the `.env` file

Example configuration:

```bash
# Keycloak settings
KEYCLOAK_VERSION=26.4.2
KEYCLOAK_PORT=8080

# Local development
KC_BOOTSTRAP_ADMIN_USERNAME=admin
KC_BOOTSTRAP_ADMIN_PASSWORD=admin
KC_PROXY=edge
KC_HOSTNAME_STRICT=false
KC_HOSTNAME_STRICT_HTTPS=false
KC_HTTP_ENABLED=true
KC_HTTP_RELATIVE_PATH=/
KC_HOSTNAME_URL=http://leoid.example.com
KC_PROXY_HEADERS=xforwarded
```

These variables control the container startup and Keycloak’s hostname behavior.

Keycloak uses the shared PostgreSQL 18 container on the `leo-vlan` Docker
network. Its database is `keycloak` inside that PostgreSQL container; port
5432 is the internal PostgreSQL port and is separate from LEO BOT's host port
5433.

---

### 3. Make the script executable

```bash
chmod +x run-keycloak.sh
```

---

### 4. Run Keycloak

**Normal mode (safe restart, keep data):**

```bash
./run-keycloak.sh
```

**Reset mode (remove container + delete data):**

```bash
./run-keycloak.sh --reset
```

Behavior summary:

* If a Keycloak container exists → **restarts it**
* If no container exists → **creates a new one**
* If `--reset` flag used → **removes container and volume**, then starts fresh

---

## 🧱 Data persistence

By default, Keycloak stores its data in a Docker volume named `keycloak_data`.
This means users, realms, and configurations **persist across restarts**.

To inspect or remove the volume manually:

```bash
docker volume ls
docker volume rm keycloak_data
```

---

## 🌐 Access Keycloak

Once running, open:

```
https://leoid.example.com
```

Default credentials (from `.env`):

```
Username: admin
Password: admin
```

> The settings `KC_PROXY=edge` and `KC_PROXY_HEADERS=xforwarded` tell Keycloak that HTTPS is handled by Nginx — not inside the container.

---

## 🧩 Example Nginx configuration

```nginx
server {
    listen 443 ssl http2;
    server_name leoid.example.com;

    ssl_certificate /path/to/example.com.pem;
    ssl_certificate_key /path/to/example.com-key.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Port 443;
    }
}
```

## To make local HTTPS work for Keycloak at domain leoid.example.com


### 1. Copy the certificate, renaming it to .crt
sudo cp /path/to/example.com.pem /usr/local/share/ca-certificates/my-local-ca.crt

### 2. Update the system's certificate store
sudo update-ca-certificates

---

## 🧩 Useful commands

| Task                       | Command                     |
| -------------------------- | --------------------------- |
| Start Keycloak             | `./run-keycloak.sh`         |
| Reset & delete all data    | `./run-keycloak.sh --reset` |
| View live logs             | `docker logs -f keycloak`   |
| Stop Keycloak              | `./stop_keycloak.sh`        |
| Restart container manually | `docker restart keycloak`   |
| List Docker volumes        | `docker volume ls`          |

---

## 🔮 Future improvements

* Optional PostgreSQL integration for production
* Docker Compose setup for one-command orchestration
* Auto-restart policy (`--restart unless-stopped`)
* Health-check endpoint for monitoring tools

---

## 🧠 Summary

| Mode       | Behavior                              |
| ---------- | ------------------------------------- |
| Default    | Restarts if exists, keeps data        |
| `--reset`  | Stops, removes, and deletes volume    |
| Persistent | Data stored in `keycloak_data` volume |

Keycloak will be available at: **`https://leoid.example.com`**
