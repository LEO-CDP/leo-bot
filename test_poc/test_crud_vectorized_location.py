import asyncio
import json
import cityhash
import asyncpg
import numpy as np
from _bootstrap import PROJECT_ROOT
from leoai.ai_core import get_embedding_model

# -----------------------------
# Config
# -----------------------------
DB_DSN = "postgresql://username:password@localhost:5432/yourdb"  # Change this

model = get_embedding_model()
VECTOR_DIM_SIZE = model.dimensions

TABLE_NAME = "cities_data"

# -----------------------------
# Helper Functions
# -----------------------------
def hash_string(string: str) -> int:
    """Hashes a string into an unsigned 64-bit integer (CityHash64)."""
    return cityhash.CityHash64(string)


def normalize_vector(v: np.ndarray) -> np.ndarray:
    """Normalize embedding vectors for cosine similarity."""
    v = v.astype(np.float32)
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def to_pg_vector_literal(v: np.ndarray) -> str:
    """Convert NumPy vector to Postgres vector literal."""
    return "[" + ",".join(map(lambda x: repr(float(x)), v.tolist())) + "]"


def read_json_file(file_path: str):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading JSON: {e}")
        return []


# -----------------------------
# Database Setup
# -----------------------------
async def setup_db():
    conn = await asyncpg.connect(DB_DSN)
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id BIGINT PRIMARY KEY,
            name TEXT,
            description TEXT,
            population BIGINT,
            travel_types TEXT[],
            geom GEOMETRY(Point, 4326),
            embedding VECTOR({VECTOR_DIM_SIZE})
        );
    """)

    # Create index for ANN search and geospatial
    await conn.execute(f"""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_class WHERE relname = '{TABLE_NAME}_embedding_hnsw'
          ) THEN
            CREATE INDEX {TABLE_NAME}_embedding_hnsw
            ON {TABLE_NAME}
            USING hnsw (embedding vector_cosine_ops)
            WITH (m=16, ef_construction=200);
          END IF;
        END$$;
    """)

    await conn.execute(f"CREATE INDEX IF NOT EXISTS {TABLE_NAME}_geom_idx ON {TABLE_NAME} USING GIST (geom);")
    await conn.execute(f"CREATE INDEX IF NOT EXISTS {TABLE_NAME}_travel_types_idx ON {TABLE_NAME} USING GIN (travel_types);")

    await conn.close()


# -----------------------------
# Indexing / Insertion
# -----------------------------
async def index_data(file_path: str):
    cities = read_json_file(file_path)
    if not cities:
        print("❌ No city data found.")
        return

    pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=5)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f"TRUNCATE TABLE {TABLE_NAME};")
            for city in cities:
                city_id = hash_string(json.dumps(city))
                text_corpus = " ".join(city["travelTypes"]) + " - " + city["name"] + " - " + city["description"]

                # Vectorize description
                embedding = model.encode(text_corpus, convert_to_numpy=True)
                embedding = normalize_vector(embedding)
                emb_literal = to_pg_vector_literal(embedding)

                print(f"Indexing: {city['name']} (lat={city['lat']}, lon={city['lon']})")

                await conn.execute(
                    f"""
                    INSERT INTO {TABLE_NAME} (id, name, description, population, travel_types, geom, embedding)
                    VALUES ($1, $2, $3, $4, $5, ST_SetSRID(ST_MakePoint($6, $7), 4326), $8::vector)
                    ON CONFLICT (id) DO UPDATE
                      SET name = EXCLUDED.name,
                          description = EXCLUDED.description,
                          population = EXCLUDED.population,
                          travel_types = EXCLUDED.travel_types,
                          geom = EXCLUDED.geom,
                          embedding = EXCLUDED.embedding;
                    """,
                    city_id,
                    city["name"],
                    city["description"],
                    city["population"],
                    city["travelTypes"],
                    city["lon"],
                    city["lat"],
                    emb_literal,
                )
    await pool.close()
    print("✅ City data indexed successfully.")


# -----------------------------
# Query Function
# -----------------------------
async def run_query(
    query_text: str,
    radius_in_km: float,
    geo_location: dict,
    travel_types=None,
    avg_population: int = 10_000_000,
):
    if travel_types is None:
        travel_types = []

    pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        # Encode query
        query_emb = model.encode(query_text, convert_to_numpy=True)
        query_emb = normalize_vector(query_emb)
        query_literal = to_pg_vector_literal(query_emb)

        print(f"\nRunning query: '{query_text}'")

        sql = f"""
        SELECT
            name,
            description,
            population,
            travel_types,
            ST_Y(geom) AS lat,
            ST_X(geom) AS lon,
            1 - (embedding <=> $1::vector) AS similarity,
            ST_DistanceSphere(geom, ST_MakePoint($2, $3)) / 1000 AS distance_km
        FROM {TABLE_NAME}
        WHERE
            population < $4
            AND (
                cardinality($5::text[]) = 0 OR travel_types && $5::text[]
            )
            AND ST_DWithin(geom::geography, ST_MakePoint($2, $3)::geography, $6 * 1000)
        ORDER BY similarity DESC
        LIMIT 5;
        """

        rows = await conn.fetch(sql, query_literal, geo_location["lon"], geo_location["lat"], avg_population, travel_types, radius_in_km)

        if not rows:
            print("⚠️ No results found.")
        else:
            print(f"\nTop {len(rows)} Results:")
            for i, row in enumerate(rows, 1):
                print(
                    f"{i}: {row['name']} ({row['distance_km']:.1f} km away) "
                    f"- pop={row['population']} "
                    f"- score={row['similarity']:.4f}"
                )
                print(f"   {row['description']}")

    await pool.close()
    return rows


# -----------------------------
# Main
# -----------------------------
async def main():
    file_path = "./data/top_cities_vietnam.json"

    await setup_db()
    await index_data(file_path)

    query = "Any travel place with cool climate and sunny beach"
    radius_in_km = 1000
    avg_population = 1_000_000
    geo_location = {"lat": 10.7619578, "lon": 106.6873586}
    categories = ["History", "Nightlife"]

    results = await run_query(query, radius_in_km, geo_location, categories, avg_population)

    print("\n\nQuery:", query)
    for i, r in enumerate(results, 1):
        print(f"{i}: {r['name']} — {r['description']}")


if __name__ == "__main__":
    asyncio.run(main())
