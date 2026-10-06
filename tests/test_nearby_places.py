import asyncio
import os
from contextlib import asynccontextmanager
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from leoai import rag_db_manager
from leoai.db_utils import DATABASE_URL
from leoai.leo_datamodel import Message
from leoai.rag_agent import (
    RAGAgent,
    format_nearby_places_answer,
    is_nearby_place_question,
    nearby_place_terms,
    nearby_result_limit,
)
from leoai.rag_db_manager import ChatDBManager, NearbyLocationUnavailable


class ListParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.links.append(dict(attrs))


def places(count):
    return [
        {
            "id": index,
            "name": f"Church {index}",
            "address": f"Address {index}",
            "description": f"Description {index}",
            "distance_meters": 100 * index,
        }
        for index in range(1, count + 1)
    ]


@pytest.mark.parametrize("question,count", [
    ("what are churches near me?", rag_db_manager.NEARBY_PLACES_LIMIT),
    ("top 3 churches is near me", 3),
    ("TOP 10 CHURCHES NEAR ME?", 10),
    ("show me top 20 churches nearby", 20),
    ("show me 10 nearest churches near me", 10),
    ("3 nhà thờ gần tôi", 3),
    ("top 20 places near me", 20),
])
def test_count_and_nearby_intent(question, count):
    assert is_nearby_place_question(question)
    assert nearby_result_limit(question) == count


@pytest.mark.parametrize("question", [
    "top 0 churches near me", "top -3 churches near me",
    "top 3.5 churches near me", "show 0 churches near me",
])
def test_invalid_requested_count_is_rejected(question):
    with pytest.raises(ValueError, match="positive integer"):
        nearby_result_limit(question)


def test_api_count_override_and_default():
    assert nearby_result_limit("top 3 churches near me", 20) == 20
    assert nearby_result_limit("what are churches near me?") == rag_db_manager.NEARBY_PLACES_LIMIT
    assert Message(result_limit=20).result_limit == 20
    for value in [0, -1, True, 3.5, "20"]:
        with pytest.raises(ValidationError):
            Message(result_limit=value)


@pytest.mark.parametrize("count", [3, 10, 20])
def test_html_response_has_requested_list_shape(count):
    answer = format_nearby_places_answer(places(count), "English", ["church"], "html")
    parser = ListParser()
    parser.feed(answer)
    assert parser.tags.count("ol") == 1
    assert parser.tags.count("li") == count
    assert len(parser.links) == count
    assert "Nearby churches:" in answer
    assert f"Address {count}" in answer
    assert f"Description {count}" in answer


@pytest.mark.parametrize("name,address", [
    ("Cha Tam Church", "25 Hoc Lac, Ho Chi Minh City"),
    ("Nhà thờ Đức Bà", "Quận 1, TP.HCM"),
    ('Church & "Chapel" <test>', "Street #1? & district"),
    ("Church without address", None),
])
def test_each_strong_place_name_links_to_google_maps(name, address):
    answer = format_nearby_places_answer(
        [{"name": name, "address": address}], "English", ["church"], "html"
    )
    parser = ListParser()
    parser.feed(answer)
    assert len(parser.links) == 1
    link = parser.links[0]
    url = urlparse(link["href"])
    assert url.scheme == "https"
    assert url.netloc == "www.google.com"
    assert url.path == "/maps/search/"
    assert parse_qs(url.query) == {
        "api": ["1"],
        "query": [f"{name}, {address}" if address else name],
    }
    assert link["target"] == "_blank"
    assert link["rel"] == "noopener noreferrer"
    assert "<strong>" in answer and "</strong></a>" in answer


def test_html_escapes_database_values_and_handles_empty_results():
    records = [{
        "name": '<script>alert("name")</script>',
        "address": "<img src=x onerror=alert(1)>",
        "description": "<b>description</b>",
        "distance_meters": 123,
    }]
    answer = format_nearby_places_answer(records, "Vietnamese", ["church"], "html")
    parser = ListParser()
    parser.feed(answer)
    assert "script" not in parser.tags
    assert "img" not in parser.tags
    assert "b" not in parser.tags
    assert "&lt;script&gt;" in answer
    assert "Các nhà thờ gần bạn:" in answer
    assert format_nearby_places_answer([], "English", ["church"], "html").startswith("<p>")


def test_text_format_remains_plain_numbered_text():
    answer = format_nearby_places_answer(places(3), "English", ["church"], "text")
    assert "<ol>" not in answer
    assert "\n\n1. Church 1" in answer


def make_agent():
    agent = RAGAgent.__new__(RAGAgent)
    agent.db = SimpleNamespace(
        find_nearby_places=AsyncMock(),
        save_chat_message=AsyncMock(),
    )
    agent.context = SimpleNamespace(build_context_summary=AsyncMock())
    agent.create_geolocation_touchpoint = AsyncMock()
    agent._safe_generate = AsyncMock()
    return agent


@pytest.mark.parametrize("count", [3, 10, 20])
def test_agent_queries_database_before_any_ai_work(count):
    async def scenario():
        agent = make_agent()
        agent.db.find_nearby_places.return_value = places(count)
        answer = await agent.process_chat_message(
            "visitor", f"top {count} churches is near me",
            touchpoint_id="tp", latitude=10.747904, longitude=106.6467328,
            target_language="English", answer_in_format="html",
        )
        agent.db.find_nearby_places.assert_awaited_once_with(
            "tp", nearby_place_terms("churches"), count,
            user_id="visitor", latitude=10.747904, longitude=106.6467328,
        )
        agent.context.build_context_summary.assert_not_awaited()
        agent.create_geolocation_touchpoint.assert_not_awaited()
        agent._safe_generate.assert_not_awaited()
        assert answer.count("<li>") == count
        assert len(agent.db.save_chat_message.await_args_list) == 2
        assert all(call.kwargs["embed"] is False for call in agent.db.save_chat_message.await_args_list)

    asyncio.run(scenario())


def test_agent_requests_location_instead_of_hallucinating_results():
    async def scenario():
        agent = make_agent()
        agent.db.find_nearby_places.side_effect = NearbyLocationUnavailable()
        answer = await agent.process_chat_message(
            "visitor", "churches near me?", target_language="English",
            answer_in_format="html",
        )
        assert "share your location" in answer
        assert "<ol>" not in answer
        agent._safe_generate.assert_not_awaited()

    asyncio.run(scenario())


def mock_connection(monkeypatch):
    conn = SimpleNamespace(
        fetch=AsyncMock(return_value=[]),
        fetchrow=AsyncMock(),
        execute=AsyncMock(),
    )

    @asynccontextmanager
    async def connect():
        yield conn

    monkeypatch.setattr(rag_db_manager, "get_async_pg_conn", connect)
    return conn


@pytest.mark.parametrize("count", [3, 10, 20])
def test_sql_receives_dynamic_limit_and_coordinates(monkeypatch, count):
    async def scenario():
        conn = mock_connection(monkeypatch)
        await ChatDBManager(None).find_nearby_places(
            None, ["church", "cathedral"], count,
            user_id="visitor", latitude=10.747904, longitude=106.6467328,
        )
        sql, longitude, latitude, terms, radius, limit = conn.fetch.call_args.args
        assert "LIMIT $5" in sql
        assert "ST_DWithin" in sql
        assert "ORDER BY distance_meters" in sql
        assert terms == ["church", "cathedral"]
        assert limit == count
        assert latitude == 10.747904
        assert longitude == 106.6467328
        assert radius == rag_db_manager.NEARBY_PLACES_RADIUS_METERS
        conn.fetchrow.assert_not_awaited()

    asyncio.run(scenario())


def test_sql_resolves_only_visitor_owned_touchpoint(monkeypatch):
    async def scenario():
        conn = mock_connection(monkeypatch)
        conn.fetchrow.return_value = {"latitude": 10.747904, "longitude": 106.6467328}
        db = ChatDBManager(None)
        await db.find_nearby_places("tp", ["church"], 20, user_id="visitor")
        assert conn.fetchrow.call_args.args[1:] == ("tp", "visitor")
        assert "user_id = $2" in conn.fetchrow.call_args.args[0]
        conn.fetchrow.return_value = None
        with pytest.raises(NearbyLocationUnavailable):
            await db.find_nearby_places("other-tp", ["church"], 20, user_id="visitor")

    asyncio.run(scenario())


def test_direct_history_saving_does_not_call_embedding_provider(monkeypatch):
    async def scenario():
        conn = mock_connection(monkeypatch)
        conn.fetchrow.return_value = {"message_hash": "hash"}
        model = Mock()
        await ChatDBManager(model).save_chat_message(
            "visitor", "bot", "<ol><li>Church</li></ol>", touchpoint_id="tp", embed=False
        )
        model.encode.assert_not_called()
        conn.execute.assert_not_awaited()
        assert "INSERT INTO chat_messages" in conn.fetchrow.call_args.args[0]

    asyncio.run(scenario())


@pytest.fixture
def route_client(monkeypatch):
    from leobot_router import leobot_main_router as routes

    agent = make_agent()
    monkeypatch.setattr(routes, "rag_agent", agent)
    monkeypatch.setattr(routes, "REDIS_CLIENT", SimpleNamespace(
        hget=lambda visitor, key: "cached-tp" if key == "touchpoint_id" else None
    ))
    monkeypatch.setattr(routes, "is_safe_to_answer", lambda visitor: True)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), agent


@pytest.mark.parametrize("count", [3, 10, 20])
def test_handle_chat_returns_dynamic_html_lists(route_client, count):
    client, agent = route_client
    agent.db.find_nearby_places.return_value = places(count)
    response = client.post("/_leoai/ask", json={
        "visitor_id": "visitor", "question": f"top {count} churches is near me",
        "answer_in_language": "en",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["error_code"] == 0
    assert data["answer"].count("<li>") == count
    assert data["touchpoint_id"] == "cached-tp"
    assert agent.db.find_nearby_places.call_args.args[2] == count
    agent._safe_generate.assert_not_awaited()


def test_handle_chat_accepts_coordinates_and_api_count_override(route_client):
    client, agent = route_client
    agent.db.find_nearby_places.return_value = places(20)
    response = client.post("/_leoai/ask", json={
        "visitor_id": "visitor", "question": "top 3 churches near me?",
        "result_limit": 20, "latitude": 10.747904, "longitude": 106.6467328,
    })
    assert response.status_code == 200
    assert response.json()["answer"].count("<li>") == 20
    assert agent.db.find_nearby_places.call_args.args[2] == 20
    agent.create_geolocation_touchpoint.assert_not_awaited()


def test_handle_chat_rejects_invalid_count_and_partial_coordinates(route_client):
    client, agent = route_client
    for question in ["top 0 churches near me", "top -3 churches near me"]:
        assert client.post("/_leoai/ask", json={
            "visitor_id": "visitor", "question": question,
        }).status_code == 400
    assert client.post("/_leoai/ask", json={
        "visitor_id": "visitor", "question": "churches near me", "result_limit": 0,
    }).status_code == 422
    assert client.post("/_leoai/ask", json={
        "visitor_id": "visitor", "question": "churches near me", "latitude": 10,
    }).status_code == 400
    agent.db.find_nearby_places.assert_not_awaited()


@pytest.mark.skipif(
    os.getenv("RUN_NEARBY_DB_TESTS") != "1",
    reason="Enable explicitly for rollback-only PostGIS integration tests.",
)
def test_real_postgis_filters_orders_and_returns_requested_counts(monkeypatch):
    async def scenario():
        conn = await asyncpg.connect(DATABASE_URL)
        tx = conn.transaction()
        await tx.start()
        try:
            schema = f"nearby_test_{uuid4().hex}"
            await conn.execute(f'CREATE SCHEMA "{schema}"')
            await conn.execute(f'SET LOCAL search_path TO "{schema}", public')
            await conn.execute("""
                CREATE TABLE touchpoints (
                    touchpoint_id text, user_id text, latitude numeric, longitude numeric
                );
                CREATE TABLE places (
                    id bigserial PRIMARY KEY, name text, address text, description text,
                    category text, tags text[], geom geometry(Point, 4326)
                );
            """)
            await conn.execute(
                "INSERT INTO touchpoints VALUES ('tp', 'visitor', 10.747904, 106.6467328)"
            )
            for index in range(25):
                await conn.execute(
                    "INSERT INTO places (name, category, tags, geom) "
                    "VALUES ($1, $2, $3, ST_SetSRID(ST_MakePoint($4, $5), 4326))",
                    f"Church {index}", "church", ["Catholic"],
                    106.6467328 + index * 0.001, 10.747904,
                )
            await conn.execute(
                "INSERT INTO places (name, category, geom) VALUES "
                "('Nearby market', 'market', ST_SetSRID(ST_MakePoint(106.6467328, 10.747904), 4326)),"
                "('Far church', 'church', ST_SetSRID(ST_MakePoint(105, 21), 4326))"
            )

            @asynccontextmanager
            async def connect():
                yield conn

            monkeypatch.setattr(rag_db_manager, "get_async_pg_conn", connect)
            db = ChatDBManager(None)
            for count in [3, 10, 20]:
                rows = await db.find_nearby_places("tp", ["church"], count, user_id="visitor")
                assert len(rows) == count
                assert [row["name"] for row in rows] == [f"Church {i}" for i in range(count)]
                assert all(row["category"] == "church" for row in rows)
                distances = [row["distance_meters"] for row in rows]
                assert distances == sorted(distances)
            rows = await db.find_nearby_places(
                None, ["Catholic"], 20, user_id="visitor",
                latitude=10.747904, longitude=106.6467328,
            )
            assert len(rows) == 20
            with pytest.raises(NearbyLocationUnavailable):
                await db.find_nearby_places("tp", ["church"], 3, user_id="other")
        finally:
            await tx.rollback()
            await conn.close()

    asyncio.run(scenario())
