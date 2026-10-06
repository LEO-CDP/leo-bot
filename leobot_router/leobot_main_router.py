import time
import logging
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from leoai.leo_datamodel import GeolocationTouchpointRequest, Message
from leoai.rag_agent import RAGAgent, is_nearby_place_question, nearby_result_limit
from leoai.ai_core import is_ai_model_ready

from main_config import (
    CDP_TRACKING,
    HOSTNAME,
    LEOBOT_DEV_MODE,
    REDIS_CLIENT,
    RATE_LIMIT_WINDOW_SECONDS,
    RATE_LIMIT_MAX_MESSAGES
)

# Router and logger initialization
logger = logging.getLogger("leobot-router")
router = APIRouter()
rag_agent = RAGAgent()


# === Rate Limiting ===
def is_safe_to_answer(visitor_id: str) -> bool:
    """
    Rate-limit messages per visitor using Redis sorted sets.
    Prevents spam and excessive API usage.
    """
    key = f"chat_rate_limit:{visitor_id}"
    now = int(time.time() * 1000)
    window_start = now - (RATE_LIMIT_WINDOW_SECONDS * 1000)

    # Remove old entries from window
    REDIS_CLIENT.zremrangebyscore(key, 0, window_start)

    # If user has exceeded limit, block temporarily
    if REDIS_CLIENT.zcard(key) >= RATE_LIMIT_MAX_MESSAGES:
        return False

    # Log current message time
    REDIS_CLIENT.zadd(key, {str(now): now})
    REDIS_CLIENT.expire(key, RATE_LIMIT_WINDOW_SECONDS)
    return True


# === Core UI Routes ===
@router.get("/", response_class=HTMLResponse)
@router.get("/_leoai", response_class=HTMLResponse)
async def index(request: Request):
    """
    Root index page for the chatbot demo.
    Loads from Jinja2 template (index.html).
    """
    ts = int(time.time())
    data = {"request": request, "HOSTNAME": HOSTNAME,
            "LEOBOT_DEV_MODE": LEOBOT_DEV_MODE, "CDP_TRACKING": CDP_TRACKING, "timestamp": ts}
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "index.html", data)

# === demo-chatbot-ishop ===
@router.get("/_leoai/demo-chatbot-ishop", response_class=HTMLResponse)
async def demo_chat_in_ishop(request: Request):
    """
    Demo chatbot page for iShop UI.
    """
    ts = int(time.time())
    data = {"request": request, "HOSTNAME": HOSTNAME,
            "LEOBOT_DEV_MODE": LEOBOT_DEV_MODE, "timestamp": ts}
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "demo-chatbot-ishop.html", data)

# === chat-with-docss ===
@router.get("/chat-with-docs", response_class=HTMLResponse)
@router.get("/_leoai/chat-with-docs", response_class=HTMLResponse)
async def chat_with_docs(request: Request):
    """
    Demo chatbot chat-with-docs
    """
    ts = int(time.time())
    data = {"request": request, "HOSTNAME": HOSTNAME,
            "LEOBOT_DEV_MODE": LEOBOT_DEV_MODE, "timestamp": ts}
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "chat-with-docs.html", data)


# === Health Check Routes ===

@router.get("/ping", response_class=PlainTextResponse)
@router.get("/_leoai/ping", response_class=PlainTextResponse)
async def ping():
    """Simple service heartbeat check."""
    return "PONG"


@router.get("/_leoai/is-ready", response_class=JSONResponse)
@router.post("/_leoai/is-ready", response_class=JSONResponse)
async def is_ready():
    """Check whether the configured hosted AI provider has credentials."""
    return {"ok": is_ai_model_ready()}


# === Visitor Info Endpoint ===
@router.get("/_leoai/visitor-info", response_class=JSONResponse)
@router.get("/visitor-info", response_class=JSONResponse)
async def get_visitor_info(
    visitor_id: str = Query(...),
    name: str | None = None,
    touchpoint_id: str | None = None,
):
    """
    Fetch or update visitor info stored in Redis.
    Used to persist visitor names and touchpoints across sessions.
    """
    visitor_id = visitor_id.strip()
    if not visitor_id:
        return JSONResponse(status_code=400, content={"error": "visitor_id is empty"})

    redis_data = REDIS_CLIENT.hgetall(visitor_id)
    cached_name = redis_data.get("name", "")
    cached_touchpoint = redis_data.get("touchpoint_id", "")

    # Update cache only if new values differ
    updates = {}
    if name and name != cached_name:
        updates["name"] = name
    if touchpoint_id and touchpoint_id != cached_touchpoint:
        updates["touchpoint_id"] = touchpoint_id
    if updates:
        REDIS_CLIENT.hset(visitor_id, mapping=updates)

    return {
        "visitor_id": visitor_id,
        "name": name or cached_name or "",
        "init_touchpoint_id": touchpoint_id or cached_touchpoint or "",
        "cached": bool(redis_data),
        "error_code": 0
    }


@router.post("/_leoai/touchpoint/geolocation", response_class=JSONResponse)
@router.post("/touchpoint/geolocation", response_class=JSONResponse)
async def create_geolocation_touchpoint(
    payload: GeolocationTouchpointRequest,
):
    """Create/update a geolocation touchpoint and return nearby places."""
    result = await rag_agent.create_geolocation_touchpoint(
        payload.visitor_id.strip(),
        payload.latitude,
        payload.longitude,
        payload.touchpoint_id,
        payload.name,
        payload.description,
        payload.type,
        payload.keywords,
    )
    REDIS_CLIENT.hset(
        payload.visitor_id.strip(),
        mapping={"touchpoint_id": result["touchpoint_id"]},
    )
    return result


# === Main Chat API ===
@router.post("/_leoai/ask", response_class=JSONResponse)
@router.post("/ask", response_class=JSONResponse)
async def handle_chat(msg: Message):
    """
    Main endpoint for user → AI chat messages.
    Handles rate-limiting, message length validation, and response generation.
    """
    visitor_id = msg.visitor_id.strip()
    if not visitor_id:
        return {"error": True, "error_code": 500, "answer": "visitor_id is empty"}

    if len(msg.question) > 1000:
        return {"error": True, "error_code": 510, "answer": "Question too long"}
    if not msg.question.strip():
        return {"error": True, "error_code": 400, "answer": "Question is empty"}

    nearby_search = is_nearby_place_question(msg.question)
    result_limit = msg.result_limit
    if nearby_search:
        try:
            result_limit = nearby_result_limit(msg.question, result_limit)
        except ValueError as exc:
            logger.warning("Invalid nearby-place count: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if (msg.latitude is None) != (msg.longitude is None):
        raise HTTPException(status_code=400, detail="latitude and longitude must be provided together")

    profile_id = REDIS_CLIENT.hget(visitor_id, "profile_id")
    if not is_safe_to_answer(visitor_id):
        return {"error": True, "error_code": 429, "answer": "Too many messages"}

    touchpoint_id = msg.touchpoint_id or REDIS_CLIENT.hget(visitor_id, "touchpoint_id")
    if (
        touchpoint_id is None
        and msg.latitude is not None
        and msg.longitude is not None
        and not nearby_search
    ):
        touchpoint = await rag_agent.create_geolocation_touchpoint(
            visitor_id, msg.latitude, msg.longitude
        )
        touchpoint_id = touchpoint["touchpoint_id"]

    answer = await rag_agent.process_chat_message(
        user_id=visitor_id,
        user_message=msg.question,
        persona_id=msg.persona_id,
        cdp_profile_id=profile_id,
        touchpoint_id=touchpoint_id,
        target_language=msg.answer_in_language,
        answer_in_format=msg.answer_in_format,
        latitude=msg.latitude,
        longitude=msg.longitude,
        touchpoint_name=msg.touchpoint_name,
        touchpoint_description=msg.touchpoint_description,
        touchpoint_type=msg.touchpoint_type,
        touchpoint_keywords=msg.touchpoint_keywords,
        result_limit=result_limit,
    )
    return {
        "question": msg.question,
        "answer": answer,
        "visitor_id": visitor_id,
        "touchpoint_id": touchpoint_id,
        "error_code": 0,
    }
