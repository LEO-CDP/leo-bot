import os
import json
import logging
from typing import Dict, Any, List

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from leoai.ai_core import GeminiClient, get_embedding_model
from leoai.db_utils import get_pg_conn

logger = logging.getLogger("ai_index")

DATABASE_URL = os.getenv( "POSTGRES_URL", "postgresql://postgres:password@localhost:5432/customer360")

DEFAULT_MODEL_ID = os.getenv("GEMINI_TEXT_MODEL_ID", "gemini-2.0-flash-001")
EMBEDDING_MODEL_ID = os.getenv("GEMINI_EMBED_MODEL_ID", "text-embedding-004")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

embedding_model = get_embedding_model()


# -----------------------------
# ContentIndex Class
# -----------------------------
class ContentIndex:
    """
    Handles:
    - Extracting structured TOC with Gemini
    - Embedding with Gemini
    - Persisting JSON TOC + embedding into PostgreSQL (pgvector)
    - Running similarity search queries
    """

    def __init__(self, gemini_client: GeminiClient):
        self.gemini = gemini_client
        self._init_db()

    def _init_db(self):
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS page_index (
                        id SERIAL PRIMARY KEY,
                        page_number INT,
                        toc JSONB,
                        embedding VECTOR(768)  -- embedding size for Gemini text-embedding-004
                    );
                """)
                conn.commit()

    def extract_toc(self, text: str) -> Dict[str, Any]:
        prompt = f"""
        Extract a structured JSON Table of Contents from the following text.
        Use hierarchy with 'title', 'sections', 'subsections' if available.

        Text:
        {text}
        """
        response_text = self.gemini.generate_content(prompt, on_error="{}")
        try:
            return json.loads(response_text)
        except Exception:
            logger.warning("Failed to parse TOC as JSON, returning raw text instead.")
            return {"raw_text": response_text}

    def save_page(self, page_number: int, toc: Dict[str, Any]) -> int:
        toc_text = json.dumps(toc, ensure_ascii=False)
        vector = embedding_model.encode(toc_text, normalize_embeddings=True).tolist()
        
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO page_index (page_number, toc, embedding)
                    VALUES (%s, %s, %s::vector)
                    RETURNING id;
                """, (page_number, Jsonb(toc), vector))
                new_id = cur.fetchone()[0]
                conn.commit()
                return new_id

    def query_similar(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        vector = embedding_model.encode(query, normalize_embeddings=True).tolist()
        if not vector:
            return []

        with get_pg_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("""
                    SELECT id, page_number, toc, embedding <-> %s::vector AS distance
                    FROM page_index
                    ORDER BY embedding <-> %s::vector
                    LIMIT %s;
                """, (vector, vector, top_k))

                results = cur.fetchall()
                return results


