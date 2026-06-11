# 🤖 LeoBot — AI Chat Assistant for Businesses & Users

![LeoBot Screenshot](screenshot/leobot.png)

**LeoBot** is a FastAPI-based AI chatbot platform for intelligent, real-time conversations across multiple channels — including **websites**, **Facebook Messenger**, and **Zalo Official Accounts**.
It integrates seamlessly with **LEO CDP (Customer Data Platform)** to serve both **admins** and **end-users**, delivering contextual, personalized answers powered by **RAG (Retrieval-Augmented Generation)** and advanced AI models like **Google Gemini**.

---

## 🌐 Live Chatbot Demo

Try the chatbot in action:
👉 [https://leobot.leocdp.com](https://leobot.leocdp.com)

LeoBot uses the **Google Gemini API** for natural, context-aware responses.

---

## 🚀 Features

* **Multi-channel support:** Works with Facebook Messenger and Zalo OA.
* **Gemini-powered intelligence:** Uses Google Gemini API for high-quality understanding and generation.
* **RAG-based reasoning:** Combines knowledge retrieval with semantic memory.
* **FastAPI backend:** Lightweight, async, and production-ready.
* **Redis rate limiting:** Prevents spam and message floods.
* **Custom personas:** Supports user profiles, roles, and chat touchpoints.
* **Prebuilt frontend demos:** Jinja2 templates for quick UI testing and embedding.

---

## 🧠 Architecture Overview

*(Coming soon — overview diagram and explanation of key modules.)*

---

## 🧩 Key Components

### RAGAgent

Handles message understanding, context retrieval, and Gemini-based response generation.

### Webhooks

* `/fb-webhook` — Facebook Messenger
* `/zalo-webhook` — Zalo Official Account

### Redis Rate Limiting

Uses a sorted-set time window to prevent excessive messaging per user.

---

## 🛠️ Setup and Installation

### 1. Clone the Repository

```bash
git clone https://github.com/trieu/leo-bot
cd leo-bot
```

### 2. Start PostgreSQL + pgvector (via Docker)

Make sure **Docker CLI** is installed:

```bash
docker --version
```

Then start the database:

```bash
./dockers/pgsql/start_pgsql_pgvector.sh
```

This script:

* Launches a PostgreSQL 16 container (`pgsql16_vector`)
* Mounts a persistent volume (`pgdata_vector`)
* Enables **pgvector** and **postgis** extensions
* Creates the `customer360` database and schema
* Handles collation version fixes automatically

To **reset the database**, run:

```bash
./dockers/pgsql/start_pgsql_pgvector.sh --reset-db
```

You can connect manually:

```bash
psql -h localhost -U postgres -d customer360
```

---

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

Create a `.env` file or edit `main_config.py`:

```bash
# Core LEO BOT
LEOBOT_DEV_MODE=true
HOSTNAME=leobot.example.com
POSTGRES_URL=postgresql://postgres:password@localhost:5432/customer360

# Google API
GOOGLE_APPLICATION_CREDENTIALS= 
GEMINI_API_KEY= 

# Set Redis HOST and PORT 
REDIS_USER_SESSION_HOST=localhost
REDIS_USER_SESSION_PORT=6379

# Set SMTP email information
SMTP_HOST=""
SMTP_PORT=587    
SMTP_USER="" 
SMTP_PASSWORD=""  
USE_TLS=true 

# in dev, disable HTTPS check certification
PYTHONHTTPSVERIFY=1

# Keycloak for leobot client at DEV mode
KEYCLOAK_ENABLED=false
KEYCLOAK_URL=https://leoid.example.com
KEYCLOAK_REALM=master
KEYCLOAK_CLIENT_ID=leobot
KEYCLOAK_CLIENT_SECRET=""
KEYCLOAK_CALLBACK_URL=https://leobot.example.com/_leoai/sso/callback
KEYCLOAK_VERIFY_SSL=false

# Set your Facebook Page Access here
FB_VERIFY_TOKEN=""
FB_PAGE_ACCESS_TOKEN=""
```

**Gemini API setup:**

* Get your API key at [Google AI Studio](https://aistudio.google.com/app/library)
* For translation and related APIs, set up credentials in the [Google Cloud Console](https://console.cloud.google.com/apis/api/translate.googleapis.com/credentials)

---

### 5. Python Environment (Ubuntu Example)

```bash
sudo apt install python-is-python3 python3.10-venv
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

After installation, refresh your shell.

---

### 6. Run LeoBot

Production mode:

```bash
./start_app.sh
```

Development mode:

```bash
./start_dev.sh
```

LeoBot will run at `0.0.0.0:8888`.
Open your browser and visit your configured `HOSTNAME` to test.

---

## 🌐 API Endpoints

| Endpoint            | Method   | Description                      |
| ------------------- | -------- | -------------------------------- |
| `/_leoai/ask`              | POST     | Main chatbot endpoint            |
| `/_leoai/is-ready`         | GET/POST | Gemini API readiness check       |
| `/_leoai/fb-webhook`       | GET/POST | Facebook Messenger webhook       |
| `/_leoai/zalo-webhook`     | POST     | Zalo OA webhook                  |
| `/_leoai/ping`             | GET      | Basic health check               |
| `/_leoai/visitor-info` | GET      | Retrieve visitor info from Redis |

---

## 🧰 Developer Notes

* Built on **FastAPI** with full async I/O.
* Message context stored in **Redis**.
* Embeddings via **SentenceTransformer** or **Gemini Embeddings**.
* Compatible with **pgvector** and other vector databases.

To extend LeoBot:

* Add webhook routes for new channels (Telegram, LINE, etc.)
* Create custom response modules in `rag_agent`
* Integrate new LLM APIs or plugins

---

## 🧪 Testing

Run automated tests:

```bash
pytest
```

Or test manually:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"visitor_id": "demo", "question": "Hello!", "persona_id": "test"}'
```

---

## 🧭 Author & Resources

**Author:** [Trieu Nguyen](https://github.com/trieu)
**YouTube:** [@bigdatavn](https://www.youtube.com/@bigdatavn)
**Demo:** [https://leobot.leocdp.com](https://leobot.leocdp.com)

---

## 🌱 Future Roadmap

* [ ] Support Telegram, LINE, and WhatsApp
* [ ] Add knowledge-graph search (PostgreSQL + pgvector)
* [ ] Streaming chat via SSE/WebSocket
* [ ] AI analytics dashboard for admins
* [ ] Plugin SDK for external integrations

---

## 📜 License

MIT License — free to use, modify, and share.
Attribution is appreciated but not required..

---

## 💡 Vision

LeoBot embodies the union of **Dataism** and **AI pragmatism** — an assistant that connects people and data through natural conversation.
It’s not just automation; it’s augmentation — amplifying human understanding through intelligent dialogue.
