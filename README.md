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

* Launches a PostgreSQL 18 container (`pgsql18_vector`)
* Mounts a persistent volume (`pgdata_vector18`)
* Enables **pgvector** and **postgis** extensions
* Creates the `leo360` database and schema
* Handles collation version fixes automatically

To **reset the database**, run:

```bash
./dockers/pgsql/start_pgsql_pgvector.sh --reset-db
```

The PostgreSQL 16 to 18 upgrade is a fresh initialization: `--reset-db` removes
the old `pgsql16_vector` container and `pgdata_vector` volume before creating
the PostgreSQL 18 database. This permanently deletes the old database data.

You can connect manually:

```bash
psql -h localhost -p 5433 -U postgres -d leo360
```

### 3. Configure Environment

Create a `.env` file or edit `main_config.py`:

```bash
# Core LEO BOT
LEOBOT_DEV_MODE=true
HOSTNAME=leobot.example.com
AI_PROVIDER=google
# For OpenAI: set AI_PROVIDER=openai and OPENAI_API_KEY.
# For OpenRouter: set AI_PROVIDER=openrouter and OPENROUTER_API_KEY.
# Optional embedding overrides: EMBEDDING_PROVIDER, EMBEDDING_MODEL,
# EMBEDDING_DIMENSIONS (defaults to 768 to match the database vector columns).
# EMBEDDING_API_KEY can override the provider-specific embedding key.
PGSQL_DB_URL=postgresql://postgres:password@localhost:5433/leo360

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

### 4. Python Environment (Ubuntu Example)

```bash
sudo apt install python-is-python3 python3.12-venv
python3.12 -m venv env
source env/bin/activate
pip install -r requirements.txt
```

This project uses Python **3.12** for both development and production. The
startup scripts reject environments running another Python minor version.

After installation, refresh your shell.

---


### 5. Run LeoBot

Production mode:

```bash
./start_app.sh
```

To initialize or refresh the 50 Ho Chi Minh City sample places:

```bash
./start_app.sh --seed-data
```

To replace the old PostgreSQL 16 data with a fresh PostgreSQL 18 database:

```bash
./start_app.sh --reset-db
```

The reset option is destructive and must be passed explicitly.

Development mode:

```bash
./start_dev.sh
```

Development mode with sample place data:

```bash
./start_dev.sh --seed-data
```

LeoBot will run at `0.0.0.0:8888`.
Open your browser and visit your configured `HOSTNAME` to test.

---

## 🌐 API Endpoints

| Endpoint            | Method   | Description                      |
| ------------------- | -------- | -------------------------------- |
| `/_leoai/ask`              | POST     | Main chatbot endpoint            |
| `/_leoai/is-ready`         | GET/POST | Configured AI provider readiness check |
| `/_leoai/touchpoint/geolocation` | POST | Create/update a geolocation touchpoint and return nearby places |
| `/_leoai/fb-webhook`       | GET/POST | Facebook Messenger webhook       |
| `/_leoai/zalo-webhook`     | POST     | Zalo OA webhook                  |
| `/_leoai/ping`             | GET      | Basic health check               |
| `/_leoai/visitor-info` | GET      | Retrieve visitor info from Redis |

### Nearby-place questions

`/_leoai/ask` recognizes requests such as “what are churches near me?”,
“top 3 churches is near me”, and “top 20 churches nearby”. The count in the
question is passed as a SQL parameter, not fixed in the query. If no count is
specified, `NEARBY_PLACES_LIMIT` supplies the default.

```json
{
  "visitor_id": "visitor-id",
  "question": "top 10 churches near me",
  "latitude": 10.747904,
  "longitude": 106.6467328,
  "answer_in_language": "en",
  "answer_in_format": "html"
}
```

An optional positive integer `result_limit` overrides the count in the question.
The search uses supplied coordinates or the visitor's saved touchpoint, keyword
matches in place names/categories/descriptions/tags, and PostGIS radius/distance
filtering. Results are nearest-first; there may be fewer than requested within
`NEARBY_PLACES_RADIUS_METERS`. Missing location prompts the visitor to share it.
HTML answers contain an escaped ordered list (`<ol>` / `<li>`); `text` answers
remain numbered plain text. Each bold place name in an HTML answer links to a
Google Maps search using its name and address. Nearby searches query PostgreSQL directly without
AI generation, summarization, or embedding requests.

When a greeting presents the five-place picker, the backend saves the exact
numbered choices. Choosing `4` saves that place as `selected_place` for the
visitor/touchpoint conversation. Short follow-ups such as “history”, “lịch sử”,
or “opening hours” use the selected place as their subject, even after summary
refreshes or nearby-result reordering. Numeric replies can explicitly change the
selection. The prompt distinguishes stored place facts from uncertain background
information; selection alone does not provide verified historical dates/hours.

Offline tests:

```bash
env/bin/python -m pytest -q tests/test_nearby_places.py tests/test_place_selection.py
env/bin/python -m pytest -q tests/test_conversation_context.py tests/test_ai_core.py
node --test tests/leocdp.chatbot.test.cjs
```

Optional PostGIS validation uses a temporary schema that is rolled back:

```bash
RUN_NEARBY_DB_TESTS=1 env/bin/python -m pytest -q tests/test_nearby_places.py
```

Selection persistence can also be tested against PostgreSQL with fake embeddings
in a rollback-only schema:

```bash
RUN_CONVERSATION_DB_TESTS=1 env/bin/python -m pytest -q tests/test_conversation_context.py
```

---

## 🧰 Developer Notes

* Built on **FastAPI** with full async I/O.
* Message context stored in **Redis**.
* Hosted embeddings via Google GenAI, OpenAI, or OpenRouter.
* Touchpoint metadata embeddings use a separate 768-dimensional configuration;
  existing chat/context embeddings remain 768-dimensional.
* Compatible with **pgvector** and other vector databases.
* The browser chatbot can request HTML5 geolocation permission. Coordinates are
  stored as PostGIS touchpoints, and nearby rows from `places` are included in
  the conversation context. If permission is denied, normal chat continues
  without location context.

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
