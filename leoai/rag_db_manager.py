import asyncio
import json
import logging
import os
from typing import Sequence
from uuid import uuid4
from leoai.ai_core import (
    TOUCHPOINT_EMBEDDING_DIMENSIONS,
    get_touchpoint_embedding_model,
)
from leoai.db_utils import get_async_pg_conn, sha256_hash, to_pgvector

logger = logging.getLogger("ChatDB")
NEARBY_PLACES_RADIUS_METERS = int(
    os.getenv("NEARBY_PLACES_RADIUS_METERS", "50000")
)
NEARBY_PLACES_LIMIT = int(os.getenv("NEARBY_PLACES_LIMIT", "5"))
TOUCHPOINT_NAME_DEFAULT = "Web visitor"
TOUCHPOINT_TYPE_DEFAULT = "web"


class NearbyLocationUnavailable(ValueError):
    """The visitor has not supplied coordinates or an owned location touchpoint."""


def build_touchpoint_embedding_text(
    name: str | None,
    description: str | None,
    touchpoint_type: str | None,
    keywords: Sequence[str] | None,
) -> str:
    """Build stable text for a touchpoint's dedicated embedding."""
    parts = [
        f"name: {(name or '').strip()}",
        f"description: {(description or '').strip()}",
        f"type: {(touchpoint_type or '').strip()}",
        f"keywords: {', '.join(keyword.strip() for keyword in (keywords or []) if keyword.strip())}",
    ]
    return "\n".join(parts)

class ChatDBManager:
    def __init__(self, embedding_model):
        self.embedding_model = embedding_model

    async def upsert_geolocation_touchpoint(
        self,
        user_id: str,
        latitude: float,
        longitude: float,
        touchpoint_id: str | None = None,
        tenant_id: str = "default",
        name: str = TOUCHPOINT_NAME_DEFAULT,
        description: str = "",
        touchpoint_type: str = TOUCHPOINT_TYPE_DEFAULT,
        keywords: Sequence[str] = (),
    ) -> dict:
        """Persist a visitor location and return nearby PostGIS places."""
        if not user_id.strip():
            raise ValueError("user_id must be non-empty")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("latitude or longitude is out of range")
        if len(touchpoint_type) > 50:
            raise ValueError("touchpoint type must be 50 characters or fewer")
        if any(not isinstance(keyword, str) or not keyword.strip() for keyword in keywords):
            raise ValueError("touchpoint keywords must be non-empty strings")

        touchpoint_id = touchpoint_id or str(uuid4())
        embedding_model = get_touchpoint_embedding_model()
        embedding = await asyncio.to_thread(
            embedding_model.encode,
            build_touchpoint_embedding_text(
                name, description, touchpoint_type, keywords
            ),
            normalize_embeddings=True,
        )
        embedding_vector = embedding.tolist()
        if len(embedding_vector) != TOUCHPOINT_EMBEDDING_DIMENSIONS:
            raise ValueError(
                "touchpoint embedding must have "
                f"{TOUCHPOINT_EMBEDDING_DIMENSIONS} dimensions; "
                f"got {len(embedding_vector)}"
            )
        embedding_str = to_pgvector(embedding_vector)
        async with get_async_pg_conn() as conn:
            await conn.execute(
                """
                INSERT INTO touchpoints (
                    touchpoint_id, user_id, tenant_id, latitude, longitude, geom,
                    name, description, type, keywords, embedding,
                    updated_at, last_seen_at
                )
                VALUES (
                    $1, $4, $5, $2, $3,
                    ST_SetSRID(ST_MakePoint(
                        $7::double precision, $6::double precision
                    ), 4326),
                    $8, $9, $10, $11, $12::vector,
                    NOW(), NOW()
                )
                ON CONFLICT (touchpoint_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    tenant_id = EXCLUDED.tenant_id,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    geom = EXCLUDED.geom,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    type = EXCLUDED.type,
                    keywords = EXCLUDED.keywords,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW(),
                    last_seen_at = NOW();
                """,
                touchpoint_id,
                latitude,
                longitude,
                user_id,
                tenant_id,
                latitude,
                longitude,
                name,
                description,
                touchpoint_type,
                list(keywords),
                embedding_str,
            )
            places = await conn.fetch(
                """
                SELECT id, name, address, description, category, tags,
                       ST_Distance(
                           geom::geography,
                           ST_SetSRID(ST_MakePoint(
                               $2::double precision, $1::double precision
                           ), 4326)::geography
                       ) AS distance_meters
                FROM places
                WHERE ST_DWithin(
                    geom::geography,
                    ST_SetSRID(ST_MakePoint(
                        $2::double precision, $1::double precision
                    ), 4326)::geography,
                    $3
                )
                ORDER BY geom::geography <-> ST_SetSRID(ST_MakePoint(
                    $2::double precision, $1::double precision
                ), 4326)::geography
                LIMIT $4;
                """,
                latitude,
                longitude,
                NEARBY_PLACES_RADIUS_METERS,
                NEARBY_PLACES_LIMIT,
            )

        return {
            "touchpoint_id": touchpoint_id,
            "latitude": latitude,
            "longitude": longitude,
            "nearby_places": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "address": row["address"],
                    "description": row["description"],
                    "category": row["category"],
                    "tags": row["tags"] or [],
                    "distance_meters": round(float(row["distance_meters"]), 1),
                }
                for row in places
            ],
        }

    async def get_touchpoint_context(self, touchpoint_id: str | None) -> dict | None:
        if not touchpoint_id:
            return None
        async with get_async_pg_conn() as conn:
            row = await conn.fetchrow(
                """
                SELECT touchpoint_id, latitude, longitude, name, description,
                       type, keywords
                FROM touchpoints
                WHERE touchpoint_id = $1;
                """,
                touchpoint_id,
            )
            if not row:
                return None
            places = await conn.fetch(
                """
                SELECT id, name, address, description, category, tags,
                       ST_Distance(
                           geom::geography,
                           ST_SetSRID(ST_MakePoint(
                               $2::double precision, $1::double precision
                           ), 4326)::geography
                       ) AS distance_meters
                FROM places
                WHERE ST_DWithin(
                    geom::geography,
                    ST_SetSRID(ST_MakePoint(
                        $2::double precision, $1::double precision
                    ), 4326)::geography,
                    $3
                )
                ORDER BY geom::geography <-> ST_SetSRID(
                    ST_MakePoint(
                        $2::double precision, $1::double precision
                    ), 4326
                )::geography
                LIMIT $4;
                """,
                row["latitude"],
                row["longitude"],
                NEARBY_PLACES_RADIUS_METERS,
                NEARBY_PLACES_LIMIT,
            )
        return {
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "name": row["name"],
            "description": row["description"],
            "type": row["type"],
            "keywords": row["keywords"] or [],
            "nearby_places": [
                {
                    "id": place["id"],
                    "name": place["name"],
                    "address": place["address"],
                    "description": place["description"],
                    "category": place["category"],
                    "tags": place["tags"] or [],
                    "distance_meters": round(float(place["distance_meters"]), 1),
                }
                for place in places
            ],
        }

    async def find_nearby_places(
        self,
        touchpoint_id: str | None,
        search_terms: Sequence[str] = (),
        limit: int = NEARBY_PLACES_LIMIT,
        *,
        user_id: str,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> list[dict]:
        """Find the requested number of matching places using coordinates or an owned touchpoint."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be positive")
        if (latitude is None) != (longitude is None):
            raise ValueError("latitude and longitude must be provided together")

        terms = [term.strip().lower() for term in search_terms if term.strip()]
        async with get_async_pg_conn() as conn:
            if latitude is None or longitude is None:
                location = await conn.fetchrow(
                    """
                    SELECT latitude, longitude FROM touchpoints
                    WHERE touchpoint_id = $1 AND user_id = $2;
                    """,
                    touchpoint_id,
                    user_id,
                )
                if location is None:
                    raise NearbyLocationUnavailable("A visitor location is required.")
                latitude = float(location["latitude"])
                longitude = float(location["longitude"])
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError("latitude or longitude is out of range")
            rows = await conn.fetch(
                """
                WITH location AS (
                    SELECT ST_SetSRID(ST_MakePoint(
                        $1::double precision, $2::double precision
                    ), 4326)::geography AS point
                )
                SELECT p.id, p.name, p.address, p.description, p.category, p.tags,
                       ST_Distance(p.geom::geography, t.point) AS distance_meters
                FROM places AS p
                CROSS JOIN location AS t
                WHERE ST_DWithin(p.geom::geography, t.point, $4)
                  AND (
                      cardinality($3::text[]) = 0
                      OR EXISTS (
                          SELECT 1
                          FROM unnest($3::text[]) AS term
                          WHERE lower(coalesce(p.name, '')) LIKE '%' || term || '%'
                             OR lower(coalesce(p.description, '')) LIKE '%' || term || '%'
                             OR lower(coalesce(p.category, '')) LIKE '%' || term || '%'
                             OR EXISTS (
                                 SELECT 1
                                 FROM unnest(coalesce(p.tags, ARRAY[]::text[])) AS tag
                                 WHERE lower(tag) LIKE '%' || term || '%'
                             )
                      )
                  )
                ORDER BY distance_meters, p.id
                LIMIT $5;
                """,
                longitude,
                latitude,
                terms,
                NEARBY_PLACES_RADIUS_METERS,
                limit,
            )
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "address": row["address"],
                "description": row["description"],
                "category": row["category"],
                "tags": row["tags"] or [],
                "distance_meters": round(float(row["distance_meters"]), 1),
            }
            for row in rows
        ]

    async def save_chat_message(self, user_id, role, message,
                                cdp_profile_id="_", persona_id="_",
                                touchpoint_id="_", keywords=[],
                                tenant_id="default", *, embed: bool = True):
        if not user_id or not message:
            return

        if cdp_profile_id is None:
            cdp_profile_id = "_"
        if persona_id is None:
            persona_id = "_"
        if touchpoint_id is None:
            touchpoint_id = "_"
        if keywords is None:
            keywords = []

        msg_hash = sha256_hash(f"{user_id}:{message}")
        msg_vector_str = None
        if embed:
            loop = asyncio.get_event_loop()
            msg_vector = await loop.run_in_executor(
                None,
                lambda: self.embedding_model.encode(
                    f"{role}: {message}", normalize_embeddings=True
                ).tolist()
            )
            msg_vector_str = to_pgvector(msg_vector)

        async with get_async_pg_conn() as conn:
            inserted = await conn.fetchrow("""
                INSERT INTO chat_messages
                (message_hash, user_id, cdp_profile_id, tenant_id, persona_id, touchpoint_id, role, message, keywords, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
                ON CONFLICT (message_hash) DO NOTHING
                RETURNING message_hash;
            """, msg_hash, user_id, cdp_profile_id, tenant_id, persona_id, touchpoint_id, role, message, keywords)

            if inserted and msg_vector_str is not None:
                await conn.execute("""
                    INSERT INTO chat_message_embeddings
                    (message_hash, tenant_id, embedding, created_at)
                    VALUES ($1,$2,$3::vector,NOW())
                    ON CONFLICT (message_hash) DO NOTHING;
                """, msg_hash, tenant_id, msg_vector_str)

        logger.info(f"💾 Stored {role} message for user={user_id}")

    async def save_context_summary(self, user_id: str,
                                   touchpoint_id: str,
                                   cdp_profile_id: str,
                                   summary: dict,
                                   tenant_id: str = "default") -> bool:
        """Save or update a conversational context summary (with pgvector embedding)."""
        
        if cdp_profile_id is None:
            cdp_profile_id = "_"
        if touchpoint_id is None:
            touchpoint_id = "_"

        try:
            context_json = json.dumps(summary, ensure_ascii=False)
            loop = asyncio.get_event_loop()

            # Create embedding in background thread
            embedding_vector = await loop.run_in_executor(
                None,
                lambda: self.embedding_model.encode(
                    context_json, normalize_embeddings=True
                ).tolist()
            )
            embedding_str = to_pgvector(embedding_vector)

            async with get_async_pg_conn() as conn:
                await conn.execute("""
                    INSERT INTO conversational_context (
                        user_id, touchpoint_id, cdp_profile_id, tenant_id,
                        context_data, embedding, intent_label, intent_confidence, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6::vector,
                            COALESCE($7, ''), COALESCE($8, 0.0), NOW())
                    ON CONFLICT (user_id, touchpoint_id)
                    DO UPDATE SET
                        cdp_profile_id = EXCLUDED.cdp_profile_id,
                        context_data = EXCLUDED.context_data,
                        embedding = EXCLUDED.embedding,
                        intent_label = EXCLUDED.intent_label,
                        intent_confidence = EXCLUDED.intent_confidence,
                        updated_at = NOW();
                """,
                user_id,
                touchpoint_id,
                cdp_profile_id,
                tenant_id,
                context_json,
                embedding_str,
                summary.get("intent_label"),
                summary.get("intent_confidence", 0.0)
                )

            logger.info(f"💾 Context summary saved for user={user_id}, touchpoint={touchpoint_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to save context summary: {e}")
            return False