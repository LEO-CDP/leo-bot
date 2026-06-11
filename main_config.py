import os
from contextlib import asynccontextmanager
from pathlib import Path
import secrets
from dotenv import load_dotenv
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from redis import Redis
from fastapi import Depends, FastAPI, HTTPException
from leoai.ai_core import get_embedding_model
import logging
import structlog

# Load environment variables from .env file
load_dotenv(override=True)

# --- Loggin ---
def setup_logging():
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ]
    )


# --- General ---
VERSION = "1.0.0"
SERVICE_NAME = f"LEO BOT VERSION: {VERSION}"
LEOBOT_DEV_MODE = os.getenv("LEOBOT_DEV_MODE") == "true"
CDP_TRACKING = os.getenv("CDP_TRACKING") == "true"
HOSTNAME = os.getenv("HOSTNAME", "localhost")

# --- Rate Limiting ---
RATE_LIMIT_MAX_MESSAGES = 20  # max messages
RATE_LIMIT_WINDOW_SECONDS = 60  # time window

# --- Redis ---
REDIS_HOST = os.getenv("REDIS_USER_SESSION_HOST") or "localhost"
REDIS_PORT = int(os.getenv("REDIS_USER_SESSION_PORT") or 6379)
REDIS_CLIENT = Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# --- Facebook Integration ---
BASE_URL_FB_MSG = 'https://graph.facebook.com/v13.0/me/messages'
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN")

# --- Gemini API ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Zalo OA Token ---
ZALO_OA_ACCESS_TOKEN = os.getenv("ZALO_OA_ACCESS_TOKEN")

# --- File Paths ---
BASE_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = BASE_DIR / "resources"
TEMPLATES_DIR = RESOURCES_DIR / "templates"

# lifespan of FastAPI app
@asynccontextmanager
async def leobot_lifespan(app: FastAPI):
    logger = logging.getLogger(__name__)
    # Startup logic
    logger.info("🔄 Initializing LEO BOT and loading configs ...")
    logger.info(f" HOSTNAME: {HOSTNAME}")
    logger.info(f" LEOBOT_DEV_MODE: {LEOBOT_DEV_MODE}")
    
    # start some base services for caching
    get_embedding_model()
    
    # App runs here
    yield  
    
    # Shutdown logic
    logger.info("🛑 Shutting down LEO BOT ...")
    
security = HTTPBasic()

# -----------------------------
# Basic Auth dependency
# -----------------------------
def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = "admin"  # replace with env var in production
    correct_password = "password"  # replace with env var in production

    is_valid = secrets.compare_digest(credentials.username, correct_username) and \
               secrets.compare_digest(credentials.password, correct_password)

    if not is_valid:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username