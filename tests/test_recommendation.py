import asyncio
import json
import os
import threading
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import asyncpg
import numpy as np
import pytest
from fastapi.testclient import TestClient

from test_poc import test_recommendation_api as api
from test_poc.test_recommendation import (
    Product,
    Profile,
    RecommendationConfig,
    RecommendationInputError,
    RecommendationRepository,
    RecommendationService,
    StoredProfile,
    VectorBuilder,
)


class FakeEmbeddingModel:
    dimensions = 768

    def __init__(self):
        self.calls = []
        self.threads = []

    def encode(self, sentences, *, normalize_embeddings=True):
        self.calls.append(list(sentences))
        self.threads.append(threading.get_ident())
        result = np.zeros((len(sentences), self.dimensions), dtype=np.float32)
        for index, text in enumerate(sentences):
            result[index, {"name": 0, "category": 1, "keyword": 2}.get(text, 0)] = 1
        return result


def make_repository():
    repository = MagicMock(spec=RecommendationRepository)
    repository.config = RecommendationConfig(dsn="postgresql://test", dimensions=768)
    return repository


def test_product_weights_and_profile_weights_keep_768_dimensions():
    model = FakeEmbeddingModel()
    builder = VectorBuilder(model)
    product = builder.build_product(Product("sku", "name", "category", ["keyword"]))
    profile = builder.build_profile(Profile("user", ["name"], ["category"], ["keyword"]))

    expected_product = np.zeros(768)
    expected_product[:3] = [0.5, 0.3, 0.2]
    expected_profile = np.zeros(768)
    expected_profile[:3] = [0.3, 0.4, 0.3]
    np.testing.assert_allclose(product, expected_product / np.linalg.norm(expected_product))
    np.testing.assert_allclose(profile, expected_profile / np.linalg.norm(expected_profile))
    assert product.shape == profile.shape == (768,)
    assert len(model.calls) == 2


def test_product_can_omit_category_and_keywords():
    vector = VectorBuilder(FakeEmbeddingModel()).build_product(
        Product("sku", "name", "", [])
    )
    assert vector.shape == (768,)
    assert vector[0] == 1


@pytest.mark.parametrize("dimensions", [0, 2001, 2304])
def test_config_rejects_dimensions_outside_hnsw_limit(dimensions):
    with pytest.raises(ValueError, match="HNSW vector dimensions"):
        RecommendationConfig(dsn="postgresql://test", dimensions=dimensions)


def test_config_accepts_exact_hnsw_dimension_limit():
    assert RecommendationConfig(dsn="postgresql://test", dimensions=2000).dimensions == 2000


def test_config_uses_dsn_fallback_without_exposing_credentials(monkeypatch):
    monkeypatch.setenv("PGSQL_DB_URL", "")
    monkeypatch.setenv("PGSQL_DB_URL", "postgresql://example")
    config = RecommendationConfig.from_env()
    assert config.dsn == "postgresql://example"
    assert "postgresql" not in repr(config)


def test_invalid_profile_is_not_silently_skipped():
    with pytest.raises(RecommendationInputError, match="purchase_keywords"):
        Profile("user", ["name"], [], ["keyword"])


def test_embedding_failures_propagate_and_invalid_shapes_are_rejected():
    model = FakeEmbeddingModel()
    model.encode = MagicMock(side_effect=RuntimeError("provider failed"))
    builder = VectorBuilder(model)
    with pytest.raises(RuntimeError, match="provider failed"):
        builder.build_product(Product("sku", "name", "", []))
    model.encode = MagicMock(return_value=np.ones((1, 2304)))
    with pytest.raises(ValueError, match="finite embeddings"):
        builder.build_product(Product("sku", "name", "", []))
    with pytest.raises(ValueError, match="zero"):
        builder.normalize(np.zeros(768))


def test_schema_mismatch_never_drops_tables():
    async def scenario():
        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=["vector(768)", "vector(2304)"])
        conn.transaction.return_value.__aenter__ = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        repository = RecommendationRepository(
            pool, RecommendationConfig(dsn="postgresql://test")
        )
        with pytest.raises(RuntimeError, match="no tables were dropped"):
            await repository.initialize()
        assert all("DROP" not in call.args[0] for call in conn.execute.call_args_list)

    asyncio.run(scenario())


def test_repository_decodes_asyncpg_vector_and_json_strings():
    async def scenario():
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "payload": '{"profile_id": "user", "additional_info": {"age": 30}}',
            "embedding": json.dumps([1.0] + [0.0] * 767),
        })
        conn.fetch = AsyncMock(return_value=[{
            "product_id": "sku",
            "name": "name",
            "category": "category",
            "additional_info": '{"brand": "A"}',
            "score": 0.9,
        }])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        repository = RecommendationRepository(
            pool, RecommendationConfig(dsn="postgresql://test")
        )
        stored = await repository.get_profile("user")
        assert stored.payload["additional_info"] == {"age": 30}
        assert stored.embedding.shape == (768,)
        results = await repository.search_products(stored.embedding, 3, ["skip"])
        assert results[0]["additional_info"] == {"brand": "A"}
        assert conn.fetch.call_args.args[2:] == (["skip"], 3)
        assert "ORDER BY embedding <=>" in conn.fetch.call_args.args[0]

    asyncio.run(scenario())


def test_service_single_and_batch_upserts_run_embeddings_in_worker_thread():
    async def scenario():
        main_thread = threading.get_ident()
        model = FakeEmbeddingModel()
        repository = make_repository()
        service = RecommendationService(repository, VectorBuilder(model))
        assert await service.upsert_product(Product("sku", "name", "", [])) == "sku"
        assert await service.upsert_profiles([
            Profile("user", ["name"], ["category"], ["keyword"])
        ]) == 1
        assert all(thread != main_thread for thread in model.threads)
        assert len(repository.save_products.call_args.args[0]) == 1
        assert len(repository.save_profiles.call_args.args[0]) == 1
        assert await service.upsert_products([]) == 0

    asyncio.run(scenario())


def test_service_recommendation_results_and_no_profile_case():
    async def scenario():
        repository = make_repository()
        builder = VectorBuilder(FakeEmbeddingModel())
        service = RecommendationService(repository, builder)
        repository.get_profile.return_value = None
        assert await service.recommend("missing") == {
            "profile": None, "recommended_products": []
        }
        repository.get_profile.return_value = StoredProfile(
            {"profile_id": "user"}, np.ones(768, dtype=np.float32)
        )
        repository.search_products.return_value = []
        result = await service.recommend("user", 2, ["excluded"])
        assert result == {"profile": {"profile_id": "user"}, "recommended_products": []}
        assert repository.search_products.call_args.args[1:] == (2, ["excluded"])
        assert repository.search_products.call_args.args[0].shape == (768,)
        with pytest.raises(RecommendationInputError, match="top_n"):
            await service.recommend("user", 0)

    asyncio.run(scenario())


def test_service_rebuilds_missing_profile_embedding():
    async def scenario():
        repository = make_repository()
        model = FakeEmbeddingModel()
        profile = Profile("user", ["name"], ["category"], ["keyword"])
        repository.get_profile.return_value = StoredProfile(profile.to_payload(), None)
        repository.search_products.return_value = []
        service = RecommendationService(repository, VectorBuilder(model))
        await service.recommend("user")
        assert len(model.calls) == 1
        assert repository.search_products.call_args.args[0].shape == (768,)

    asyncio.run(scenario())


def test_service_closes_pool_on_initialization_failure_and_normal_exit(monkeypatch):
    async def scenario():
        pool = MagicMock()
        pool.close = AsyncMock()
        monkeypatch.setattr(asyncpg, "create_pool", AsyncMock(return_value=pool))
        initialize = AsyncMock(side_effect=RuntimeError("bad schema"))
        monkeypatch.setattr(RecommendationRepository, "initialize", initialize)
        config = RecommendationConfig(dsn="postgresql://test")
        with pytest.raises(RuntimeError, match="bad schema"):
            async with RecommendationService.connect(config, FakeEmbeddingModel()):
                pytest.fail("Initialization should not succeed")
        pool.close.assert_awaited_once()
        pool.close.reset_mock()
        initialize.side_effect = None
        async with RecommendationService.connect(config, FakeEmbeddingModel()) as service:
            assert service.repository.pool is pool
        pool.close.assert_awaited_once()

    asyncio.run(scenario())


def test_api_uses_oop_service_and_preserves_not_found_status():
    service = MagicMock(spec=RecommendationService)
    service.upsert_profiles.return_value = 1
    service.recommend.return_value = {"profile": None, "recommended_products": []}
    api.app.dependency_overrides[api.get_service] = lambda: service
    try:
        client = TestClient(api.app)
        profile = {
            "profile_id": "user", "page_view_keywords": ["name"],
            "purchase_keywords": ["category"], "interest_keywords": ["keyword"],
        }
        assert client.post("/add-profile/", json=profile).status_code == 200
        assert client.post("/add-profiles/", json=[profile]).status_code == 200
        assert client.post("/add-product/", json={
            "product_id": "sku", "product_name": "name",
            "product_category": "category", "product_keywords": [],
        }).status_code == 200
        assert client.get("/recommend/missing").status_code == 404
        assert client.post("/recommend/", json=profile).status_code == 404
        assert client.get("/recommend/user?top_n=0").status_code == 422
        profile["profile_id"] = " "
        assert client.post("/add-profile/", json=profile).status_code == 400
    finally:
        api.app.dependency_overrides.clear()


@pytest.mark.skipif(
    os.getenv("RUN_RECOMMENDATION_DB_TESTS") != "1",
    reason="Enable explicitly to validate pgvector in a rollback-only schema.",
)
def test_postgres_hnsw_upserts_search_and_schema_checks():
    async def scenario():
        config = RecommendationConfig.from_env()
        conn = await asyncpg.connect(config.dsn)
        transaction = conn.transaction()
        await transaction.start()
        try:
            schema = f"recommendation_test_{uuid4().hex}"
            await conn.execute(f'CREATE SCHEMA "{schema}"')
            await conn.execute(f'SET LOCAL search_path TO "{schema}", public')

            class IsolatedPool:
                @asynccontextmanager
                async def acquire(self):
                    yield conn

            repository = RecommendationRepository(IsolatedPool(), config)
            await repository.initialize()
            await repository.initialize()
            assert await conn.fetchval(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid='products'::regclass AND attname='embedding'"
            ) == "vector(768)"
            assert await conn.fetchval(
                "SELECT count(*) FROM pg_indexes WHERE schemaname=$1 "
                "AND indexname='products_embedding_hnsw'", schema
            ) == 1
            service = RecommendationService(repository, VectorBuilder(FakeEmbeddingModel()))
            await service.upsert_profile(Profile(
                "user", ["name"], ["name"], ["name"], {"age": 30},
            ))
            await service.upsert_products([
                Product("match", "name", "", [], {"price": 5}),
                Product("different", "category", "", [], {"price": 10}),
            ])
            result = await service.recommend("user", 1)
            assert result["profile"]["additional_info"] == {"age": 30}
            assert result["recommended_products"][0]["product_id"] == "match"
            assert result["recommended_products"][0]["score"] == pytest.approx(1.0)
            assert result["recommended_products"][0]["additional_info"] == {"price": 5}
            await service.upsert_product(Product("match", "keyword", "", [], {"price": 7}))
            result = await service.recommend("user", 5, ["different"])
            assert len(result["recommended_products"]) == 1
            assert result["recommended_products"][0]["additional_info"] == {"price": 7}
            # pgvector's typmod stores the dimension directly, without a -4 offset.
            assert await conn.fetchval(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid='products'::regclass AND attname='embedding'"
            ) == 768
            await conn.execute("DROP INDEX products_embedding_hnsw")
            await conn.execute(
                "ALTER TABLE products ALTER COLUMN embedding TYPE vector(2304) USING NULL"
            )
            with pytest.raises(RuntimeError, match="no tables were dropped"):
                await repository.initialize()
            assert await conn.fetchval("SELECT count(*) FROM products") == 2
        finally:
            await transaction.rollback()
            await conn.close()

    asyncio.run(scenario())
