"""Hosted-embedding product recommendations backed by PostgreSQL and pgvector."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Protocol, Sequence, TypedDict

import asyncpg
import numpy as np
from numpy.typing import NDArray

if __package__:
    from . import _bootstrap
else:
    import _bootstrap

from leoai.ai_core import DEFAULT_EMBEDDING_DIMENSIONS, get_embedding_model

logger = logging.getLogger(__name__)
Vector = NDArray[np.float32]
HNSW_MAX_DIMENSIONS = 2000


class RecommendationInputError(ValueError):
    """Invalid profile, product, or search parameters supplied by a caller."""


class EmbeddingModel(Protocol):
    dimensions: int

    def encode(
        self, sentences: Sequence[str], *, normalize_embeddings: bool = True
    ) -> np.ndarray: ...


@dataclass(frozen=True)
class RecommendationConfig:
    dsn: str = field(repr=False)
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    pool_min_size: int = 1
    pool_max_size: int = 10
    hnsw_m: int = 16
    hnsw_ef_construction: int = 200

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("PGSQL_DB_URL or PGSQL_DB_URL must be configured.")
        if not 1 <= self.dimensions <= HNSW_MAX_DIMENSIONS:
            raise ValueError(
                f"HNSW vector dimensions must be between 1 and {HNSW_MAX_DIMENSIONS}."
            )
        if not 1 <= self.pool_min_size <= self.pool_max_size:
            raise ValueError("Pool sizes must satisfy 1 <= min_size <= max_size.")
        if not 2 <= self.hnsw_m <= 100:
            raise ValueError("HNSW m must be between 2 and 100.")
        if not 2 * self.hnsw_m <= self.hnsw_ef_construction <= 1000:
            raise ValueError("HNSW ef_construction must be between 2 * m and 1000.")

    @classmethod
    def from_env(cls) -> RecommendationConfig:
        return cls(dsn=os.getenv("PGSQL_DB_URL") or os.getenv("PGSQL_DB_URL") or "")


def _validate_keywords(keywords: Sequence[str], name: str) -> None:
    if isinstance(keywords, str) or any(
        not isinstance(keyword, str) or not keyword.strip() for keyword in keywords
    ):
        raise RecommendationInputError(f"{name} must contain only non-empty strings.")


@dataclass(frozen=True)
class Profile:
    profile_id: str
    page_view_keywords: Sequence[str]
    purchase_keywords: Sequence[str]
    interest_keywords: Sequence[str]
    additional_info: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise RecommendationInputError("profile_id must be non-empty.")
        for name in ("page_view_keywords", "purchase_keywords", "interest_keywords"):
            keywords = getattr(self, name)
            if not keywords:
                raise RecommendationInputError(f"{name} must be non-empty.")
            _validate_keywords(keywords, name)

    def to_payload(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "page_view_keywords": list(self.page_view_keywords),
            "purchase_keywords": list(self.purchase_keywords),
            "interest_keywords": list(self.interest_keywords),
            "additional_info": self.additional_info,
        }


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    category: str
    keywords: Sequence[str]
    additional_info: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.product_id.strip():
            raise RecommendationInputError("product_id must be non-empty.")
        _validate_keywords(self.keywords, "keywords")
        if not (self.name.strip() or self.category.strip() or self.keywords):
            raise RecommendationInputError("A product must have a name, category, or keywords.")


class Recommendation(TypedDict):
    product_id: str
    product_name: str
    product_category: str
    additional_info: dict[str, Any]
    score: float | None


class RecommendationResult(TypedDict):
    profile: dict[str, Any] | None
    recommended_products: list[Recommendation]


@dataclass(frozen=True)
class StoredProfile:
    payload: dict[str, Any]
    embedding: Vector | None


class VectorBuilder:
    """Build same-sized profile/product vectors with an injectable embedding model."""

    def __init__(
        self,
        model: EmbeddingModel,
        profile_weights: tuple[float, float, float] = (0.3, 0.4, 0.3),
        product_weights: tuple[float, float, float] = (0.5, 0.3, 0.2),
    ):
        self.model = model
        self.dimensions = model.dimensions
        for weights in (profile_weights, product_weights):
            if (
                len(weights) != 3
                or not all(np.isfinite(weight) and weight >= 0 for weight in weights)
                or not np.isclose(sum(weights), 1.0)
            ):
                raise ValueError("Vector weights must be three non-negative values summing to 1.")
        self.profile_weights = profile_weights
        self.product_weights = product_weights

    def _embed(self, texts: Sequence[str]) -> Vector:
        vectors = np.asarray(
            self.model.encode(texts, normalize_embeddings=True), dtype=np.float32
        )
        if vectors.shape != (len(texts), self.dimensions) or not np.isfinite(vectors).all():
            raise ValueError(
                f"Expected {len(texts)} finite embeddings of dimension {self.dimensions}; "
                f"got {vectors.shape}."
            )
        return vectors

    def normalize(self, values: Sequence[float] | np.ndarray) -> Vector:
        vector = np.asarray(values, dtype=np.float32)
        if vector.shape != (self.dimensions,) or not np.isfinite(vector).all():
            raise ValueError(f"Expected a finite vector of dimension {self.dimensions}.")
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm == 0:
            raise ValueError("Cannot search or index a zero or non-finite embedding.")
        return (vector / norm).astype(np.float32)

    def build_profile(self, profile: Profile) -> Vector:
        groups = (
            profile.page_view_keywords,
            profile.purchase_keywords,
            profile.interest_keywords,
        )
        vectors = self._embed([text for group in groups for text in group])
        combined = np.zeros(self.dimensions, dtype=np.float32)
        offset = 0
        for keywords, weight in zip(groups, self.profile_weights):
            combined += weight * vectors[offset:offset + len(keywords)].mean(axis=0)
            offset += len(keywords)
        return self.normalize(combined)

    def build_product(self, product: Product) -> Vector:
        groups = (
            [product.name] if product.name.strip() else [],
            [product.category] if product.category.strip() else [],
            product.keywords,
        )
        vectors = self._embed([text for group in groups for text in group])
        combined = np.zeros(self.dimensions, dtype=np.float32)
        offset = 0
        for texts, weight in zip(groups, self.product_weights):
            if texts:
                combined += weight * vectors[offset:offset + len(texts)].mean(axis=0)
                offset += len(texts)
        return self.normalize(combined)


def _point_id(identifier: str) -> int:
    return int(hashlib.sha256(identifier.encode("utf-8")).hexdigest(), 16) % (10 ** 16)


def _vector_literal(vector: Vector) -> str:
    return json.dumps(vector.tolist())


def _json_object(value: str | dict[str, Any], field_name: str) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must be a JSON object.")
    return decoded


PROFILE_UPSERT_SQL = """
INSERT INTO profiles (id, profile_id, embedding, payload)
VALUES ($1, $2, $3::vector, $4::jsonb)
ON CONFLICT (id) DO UPDATE SET
    profile_id = EXCLUDED.profile_id,
    embedding = EXCLUDED.embedding,
    payload = EXCLUDED.payload;
"""

PRODUCT_UPSERT_SQL = """
INSERT INTO products (id, product_id, embedding, name, category, additional_info)
VALUES ($1, $2, $3::vector, $4, $5, $6::jsonb)
ON CONFLICT (id) DO UPDATE SET
    product_id = EXCLUDED.product_id,
    embedding = EXCLUDED.embedding,
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    additional_info = EXCLUDED.additional_info;
"""


class RecommendationRepository:
    """Own PostgreSQL queries; never make embedding API calls while holding a connection."""

    def __init__(self, pool: asyncpg.Pool, config: RecommendationConfig):
        self.pool = pool
        self.config = config

    async def initialize(self) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                for table in ("profiles", "products"):
                    actual_type = await conn.fetchval(
                        """
                        SELECT format_type(a.atttypid, a.atttypmod)
                        FROM pg_attribute a
                        JOIN pg_class c ON c.oid = a.attrelid
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = current_schema() AND c.relname = $1
                          AND a.attname = 'embedding' AND NOT a.attisdropped;
                        """,
                        table,
                    )
                    expected_type = f"vector({self.config.dimensions})"
                    if actual_type is not None and actual_type != expected_type:
                        raise RuntimeError(
                            f"{table}.embedding is {actual_type}, expected {expected_type}. "
                            "Migrate/re-embed existing data explicitly; no tables were dropped."
                        )
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS profiles (
                        id bigint PRIMARY KEY,
                        profile_id text UNIQUE,
                        embedding vector({self.config.dimensions}),
                        payload jsonb
                    );
                    CREATE TABLE IF NOT EXISTS products (
                        id bigint PRIMARY KEY,
                        product_id text UNIQUE,
                        embedding vector({self.config.dimensions}),
                        name text,
                        category text,
                        additional_info jsonb
                    );
                    CREATE INDEX IF NOT EXISTS products_embedding_hnsw
                    ON products USING hnsw (embedding vector_cosine_ops)
                    WITH (m = {self.config.hnsw_m},
                          ef_construction = {self.config.hnsw_ef_construction});
                    """
                )
        logger.info("Recommendation schema ready: dimensions=%d", self.config.dimensions)

    async def save_profiles(self, rows: Sequence[tuple[int, str, str, str]]) -> None:
        await self._save_batch(PROFILE_UPSERT_SQL, rows)

    async def save_products(
        self, rows: Sequence[tuple[int, str, str, str, str, str]]
    ) -> None:
        await self._save_batch(PRODUCT_UPSERT_SQL, rows)

    async def _save_batch(self, sql: str, rows: Sequence[tuple[Any, ...]]) -> None:
        if not rows:
            return
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(sql, rows)

    async def get_profile(self, profile_id: str) -> StoredProfile | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload, embedding::text AS embedding FROM profiles WHERE id = $1",
                _point_id(profile_id),
            )
        if row is None:
            return None
        embedding = (
            np.asarray(json.loads(row["embedding"]), dtype=np.float32)
            if row["embedding"] is not None
            else None
        )
        return StoredProfile(_json_object(row["payload"], "payload"), embedding)

    async def search_products(
        self, vector: Vector, top_n: int, excluded_ids: Sequence[str]
    ) -> list[Recommendation]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT product_id, name, category, additional_info,
                       1 - (embedding <=> $1::vector) AS score
                FROM products
                WHERE product_id <> ALL($2::text[])
                ORDER BY embedding <=> $1::vector
                LIMIT $3;
                """,
                _vector_literal(vector),
                list(excluded_ids),
                top_n,
            )
        return [
            {
                "product_id": row["product_id"],
                "product_name": row["name"],
                "product_category": row["category"],
                "additional_info": _json_object(row["additional_info"], "additional_info"),
                "score": float(row["score"]) if row["score"] is not None else None,
            }
            for row in rows
        ]


class RecommendationService:
    """Coordinate vectors and persistence; inject either dependency for tests/extensions."""

    def __init__(self, repository: RecommendationRepository, vectors: VectorBuilder):
        if repository.config.dimensions != vectors.dimensions:
            raise ValueError("Repository and embedding model dimensions must match.")
        self.repository = repository
        self.vectors = vectors

    @classmethod
    @asynccontextmanager
    async def connect(
        cls,
        config: RecommendationConfig | None = None,
        model: EmbeddingModel | None = None,
    ) -> AsyncGenerator[RecommendationService, None]:
        config = config or RecommendationConfig.from_env()
        vectors = VectorBuilder(model if model is not None else get_embedding_model())
        if vectors.dimensions != config.dimensions:
            raise ValueError("Configured dimensions do not match the embedding model.")
        pool = await asyncpg.create_pool(
            config.dsn,
            min_size=config.pool_min_size,
            max_size=config.pool_max_size,
        )
        try:
            repository = RecommendationRepository(pool, config)
            await repository.initialize()
            yield cls(repository, vectors)
        finally:
            await pool.close()

    def _profile_rows(self, profiles: Sequence[Profile]) -> list[tuple[int, str, str, str]]:
        return [
            (
                _point_id(profile.profile_id),
                profile.profile_id,
                _vector_literal(self.vectors.build_profile(profile)),
                json.dumps(profile.to_payload()),
            )
            for profile in profiles
        ]

    def _product_rows(
        self, products: Sequence[Product]
    ) -> list[tuple[int, str, str, str, str, str]]:
        return [
            (
                _point_id(product.product_id),
                product.product_id,
                _vector_literal(self.vectors.build_product(product)),
                product.name,
                product.category,
                json.dumps(product.additional_info),
            )
            for product in products
        ]

    async def upsert_profile(self, profile: Profile) -> str:
        await self.upsert_profiles([profile])
        return profile.profile_id

    async def upsert_product(self, product: Product) -> str:
        await self.upsert_products([product])
        return product.product_id

    async def upsert_profiles(self, profiles: Sequence[Profile]) -> int:
        rows = await asyncio.to_thread(self._profile_rows, profiles)
        await self.repository.save_profiles(rows)
        logger.info("Upserted %d profiles", len(rows))
        return len(rows)

    async def upsert_products(self, products: Sequence[Product]) -> int:
        rows = await asyncio.to_thread(self._product_rows, products)
        await self.repository.save_products(rows)
        logger.info("Upserted %d products", len(rows))
        return len(rows)

    async def recommend(
        self,
        profile_id: str,
        top_n: int = 8,
        excluded_ids: Sequence[str] = (),
    ) -> RecommendationResult:
        if not profile_id.strip():
            raise RecommendationInputError("profile_id must be non-empty.")
        if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n <= 0:
            raise RecommendationInputError("top_n must be a positive integer.")
        _validate_keywords(excluded_ids, "excluded_ids")
        stored = await self.repository.get_profile(profile_id)
        if stored is None:
            logger.info("No recommendation profile found for %s", profile_id)
            return {"profile": None, "recommended_products": []}
        if stored.embedding is None:
            profile = Profile(**stored.payload)
            vector = await asyncio.to_thread(self.vectors.build_profile, profile)
        else:
            vector = self.vectors.normalize(stored.embedding)
        recommendations = await self.repository.search_products(vector, top_n, excluded_ids)
        logger.info("Returned %d recommendations for %s", len(recommendations), profile_id)
        return {"profile": stored.payload, "recommended_products": recommendations}


async def main_demo() -> None:
    async with RecommendationService.connect() as service:
        await service.upsert_profile(Profile(
            "user_123",
            ["running shoes", "trail shoes", "sports footwear"],
            ["nike air running shoes"],
            ["trail running", "fitness"],
            {"age": 30},
        ))
        await service.upsert_products([
            Product(
                "sku_1001", "Trailblazer Running Shoe", "shoes",
                ["trail", "grip", "lightweight"], {"brand": "BrandA", "price": 149.99},
            ),
            Product(
                "sku_1002", "City Runner Sneaker", "shoes",
                ["city", "cushion", "casual"], {"brand": "BrandB", "price": 109.99},
            ),
        ])
        await service.upsert_profiles([
            Profile(
                "user_batch_1", ["bike helmet", "cycling shoes"], ["helmet pro"],
                ["cycling"], {"country": "VN"},
            ),
        ])
        await service.upsert_product(Product(
            "sku_2001", "Mountain Grip Shoe", "shoes",
            ["mountain", "grippy", "durable"], {"brand": "BrandC", "price": 189.0},
        ))
        result = await service.recommend("user_123", top_n=5)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main_demo())
