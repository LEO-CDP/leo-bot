import asyncio
import os
import time
import asyncpg
import numpy as np
try:
    from test_poc import _bootstrap
except ModuleNotFoundError:
    import _bootstrap
from leoai.ai_core import get_embedding_model

# ----------------------------
# PGVector configuration
# ----------------------------
DB_DSN = os.getenv("PGSQL_DB_URL", "postgresql://postgres:password@localhost:5433/leo360")

model = get_embedding_model()
VECTOR_DIM_SIZE = model.dimensions

# Corpus
corpus_list = [
    "Một người đàn ông đang ăn thức ăn.",
    "Một người đàn ông đang ăn một miếng bánh mì.",
    "Cô gái đang bế một đứa bé.",
    "Một người đàn ông đang cưỡi ngựa.",
    "Một người phụ nữ đang chơi violin.",
    "Hai người đàn ông đẩy xe xuyên rừng.",
    "Một người đàn ông đang cưỡi một con ngựa trắng trên một khu đất kín.",
    "Một con khỉ đang chơi trống.",
    "Một con báo đang chạy theo con mồi.",
    "Gia đình là tình yêu.",
    "Tình yêu ở mọi nơi.",
]

queries = [
    "tình yêu ở khắp mọi nơi ?",
    "Một người đàn ông đang ăn mì ống.",
    "Ai đó trong trang phục khỉ đột đang chơi một bộ trống.",
    "Báo là loài động vật trên nhanh nhất hành tinh.",
]

# ----------------------------
# Helper functions
# ----------------------------
def normalize_vector(v: np.ndarray) -> np.ndarray:
    """Normalize vectors for cosine similarity."""
    v = v.astype(np.float32)
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def to_pg_literal(v: np.ndarray) -> str:
    """Convert numpy array to Postgres vector literal."""
    return "[" + ",".join(map(lambda x: repr(float(x)), v.tolist())) + "]"


# ----------------------------
# Async setup + operations
# ----------------------------
async def setup_db():
    conn = await asyncpg.connect(DB_DSN)
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS text_data (
            id SERIAL PRIMARY KEY,
            text TEXT,
            embedding vector({VECTOR_DIM_SIZE})
        );
        """
    )
    # Create HNSW index for fast similarity search
    await conn.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_class WHERE relname = 'text_data_embedding_hnsw'
          ) THEN
            CREATE INDEX text_data_embedding_hnsw
            ON text_data
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 200);
          END IF;
        END$$;
        """
    )
    await conn.close()


async def insert_corpus(pool):
    """Insert all sentences + embeddings into PostgreSQL"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE TABLE text_data;")
            start = time.time()
            for idx, text in enumerate(corpus_list):
                print(f"{idx} = {text}")
                emb = model.encode(text, convert_to_numpy=True)
                emb = normalize_vector(emb)
                emb_literal = to_pg_literal(emb)
                await conn.execute(
                    "INSERT INTO text_data (text, embedding) VALUES ($1, $2::vector)",
                    text,
                    emb_literal,
                )
            end = time.time()
            print(f"=> inserted {len(corpus_list)} records in {end - start:.2f}s")


async def search_queries(pool):
    """Perform semantic search for each query."""
    async with pool.acquire() as conn:
        for query in queries:
            print("\n\n======================\n")
            print("Query:", query)
            print("\nTop 3 most similar sentences in corpus_list:")

            q_emb = model.encode(query, convert_to_numpy=True)
            q_emb = normalize_vector(q_emb)
            q_emb_literal = to_pg_literal(q_emb)

            # Perform cosine similarity search
            rows = await conn.fetch(
                f"""
                SELECT text, 1 - (embedding <=> $1::vector) AS similarity
                FROM text_data
                ORDER BY similarity DESC
                LIMIT 3;
                """,
                q_emb_literal,
            )
            for rank, r in enumerate(rows, 1):
                print(f"{rank}. {r['text']}  (score={r['similarity']:.4f})")


# ----------------------------
# Main orchestration
# ----------------------------
async def main():
    await setup_db()
    pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=5)
    await insert_corpus(pool)
    await search_queries(pool)
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
