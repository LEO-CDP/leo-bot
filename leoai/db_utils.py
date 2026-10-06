from contextlib import asynccontextmanager
import hashlib
from typing import Any, List
from dotenv import load_dotenv
import os
import psycopg
import asyncpg
import json

load_dotenv(override=True)

DEFAULT_EMBED_DIM = 768
DEFAULT_DATABASE_URL = '"postgresql://postgres:password@localhost:5433/leo360"'
DATABASE_URL = os.getenv("PGSQL_DB_URL", DEFAULT_DATABASE_URL )


# --- DB Connection ---

def get_pg_conn():
    """Synchronous psycopg3 connection"""
    return psycopg.connect(DATABASE_URL)


@asynccontextmanager
async def get_async_pg_conn():
    """Asynchronous asyncpg connection"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()


# =====================================================================
# Utility functions
# =====================================================================

def sha256_hash(text: str) -> str:
    """Generate a SHA256 hash of text to detect duplicate messages."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def to_pgvector(embedding: list[float]) -> str:
    return f"[{', '.join(map(str, embedding))}]"



def parse_embedding(raw_embedding: Any, dim: int = DEFAULT_EMBED_DIM) -> List[float]:
    """Convert raw DB embedding to List[float], replacing invalid values with 0.0."""
    if not raw_embedding:
        return [0.0] * dim
    cleaned = []
    for val in raw_embedding:
        try:
            cleaned.append(float(val))
        except (ValueError, TypeError):
            cleaned.append(0.0)
    # ensure correct length
    if len(cleaned) < dim:
        cleaned.extend([0.0] * (dim - len(cleaned)))
    elif len(cleaned) > dim:
        cleaned = cleaned[:dim]
    return cleaned

def parse_metadata(raw_metadata: Any) -> dict:
    """Convert raw DB metadata to dict, fallback to empty dict."""
    if not raw_metadata:
        return {}
    if isinstance(raw_metadata, dict):
        return raw_metadata
    try:
        return json.loads(raw_metadata)
    except (ValueError, TypeError):
        return {}

