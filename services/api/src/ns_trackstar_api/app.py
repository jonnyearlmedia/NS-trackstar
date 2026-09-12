from __future__ import annotations

import os
from asyncio import Lock
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row

LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")
TimeWindow = Literal["today", "week", "upcoming", "all"]


class ResilientDatabaseConnection:
    """Single-node connection wrapper that recovers after a database restart."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.connection: psycopg.AsyncConnection | None = None
        self._reconnect_lock = Lock()

    async def connect(self) -> None:
        self.connection = await psycopg.AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
            autocommit=True,
        )

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    async def execute(self, query, params=None):
        if self.connection is None:
            await self.connect()
        try:
            return await self.connection.execute(query, params)
        except (psycopg.InterfaceError, psycopg.OperationalError):
            failed_connection = self.connection
            async with self._reconnect_lock:
                if self.connection is failed_connection:
                    await self.close()
                    await self.connect()
            return await self.connection.execute(query, params)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    app.state.db = ResilientDatabaseConnection(database_url)
    await app.state.db.connect()
    try:
        yield
    finally:
        await app.state.db.close()


app = FastAPI(title="NS Trackstar API", version="0.1.0", lifespan=lifespan)

cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


def _time_window_sql(time_window: TimeWindow) -> tuple[str, dict[str, object]]:
    now = datetime.now(LOCAL_TIMEZONE)
    if time_window == "today":
        after = datetime.combine(now.date(), time.min, tzinfo=LOCAL_TIMEZONE)
        return "AND p.last_activity_at >= %(after)s", {"after": after}
    if time_window == "week":
        return "AND p.last_activity_at >= %(after)s", {"after": now - timedelta(days=7)}
    if time_window == "upcoming":
        return (
            """
            AND EXISTS (
              SELECT 1
              FROM project_event pe
              WHERE pe.project_id = p.id
                AND pe.occurred_at > now()
            )
            """,
            {},
        )
    return "", {}


def _project_scope(
    time_window: TimeWindow,
    project_type: str | None,
) -> tuple[str, str, dict[str, object]]:
    time_filter, time_params = _time_window_sql(time_window)
    params = dict(time_params)
    type_filter = ""
    if project_type:
        params["project_type"] = project_type
        type_filter = "AND p.project_type = %(project_type)s"
    return time_filter, type_filter, params


def _display_priority(row: dict) -> float:
    """Presentation prominence only; never interpreted as a factual project status."""

    explicit = float(row.get("importance_score") or 0)
    source_count = int(row.get("source_count") or 0)
    source_signal = min(source_count, 5) / 5 * 0.55
    type_signal = 0.12 if row.get("project_type") in {"transportation_project", "public_works"} else 0
    return round(min(1.0, max(explicit, source_signal) + type_signal), 3)


@app.get("/health")
async def health() -> dict[str, str]:
    await app.state.db.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/admin/sources/health")
async def source_health() -> list[dict]:
    cursor = await app.state.db.execute(
        """
        SELECT
          s.source_key, s.name, s.source_family, s.jurisdiction,
          sh.health_state, sh.health_reason, sh.last_attempt_at,
          sh.last_success_at, sh.last_content_change_at,
          sh.records_returned, sh.consecutive_failures,
          sh.schema_fingerprint, sh.parser_yield
        FROM source s
        LEFT JOIN source_health sh ON sh.source_id = s.id
        WHERE s.enabled = true
        ORDER BY s.jurisdiction NULLS LAST, s.name
        """
    )
    rows = await cursor.fetchall()
    return [
        {
            key: (value.isoformat() if hasattr(value, "isoformat") else value)
            for key, value in row.items()
        }
        for row in rows
    ]


@app.get("/map/projects")
async def map_projects(
    west: Annotated[float | None, Query()] = None,
    south: Annotated[float | None, Query()] = None,
    east: Annotated[float | None, Query()] = None,
    north: Annotated[float | None, Query()] = None,
    time_window: Annotated[TimeWindow, Query(alias="window")] = "week",
    project_type: Annotated[str | None, Query(max_length=80)] = None,
) -> dict:
    time_filter, type_filter, scope_params = _project_scope(time_window, project_type)
    params = dict(scope_params)
    bbox_filter = ""
    if all(value is not None for value in (west, south, east, north)):
        params.update(
            {
                "west": float(west),
                "south": float(south),
                "east": float(east),
                "north": float(north),
            }
        )
        bbox_filter = """
          AND p.primary_geometry && ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)
        """

    cursor = await app.state.db.execute(
        f"""
        SELECT
          p.id,
          p.canonical_name,
          p.project_type,
          p.last_activity_at,
          p.importance_score,
          COALESCE(sc.source_count, 0) AS source_count,
          ST_AsGeoJSON(p.primary_geometry)::json AS geometry,
          MAX(psd.value) FILTER (WHERE psd.dimension = 'delivery_stage') AS delivery_stage
        FROM project p
        LEFT JOIN project_status_dimension psd ON psd.project_id = p.id
        LEFT JOIN (
          SELECT project_id, COUNT(DISTINCT source_record_id)::int AS source_count
          FROM project_source_record
          GROUP BY project_id
        ) sc ON sc.project_id = p.id
        WHERE p.primary_geometry IS NOT NULL
        {bbox_filter}
        {time_filter}
        {type_filter}
        GROUP BY p.id, sc.source_count
        ORDER BY p.importance_score DESC, sc.source_count DESC, p.last_activity_at DESC NULLS LAST
        """,
        params,
    )
    rows = await cursor.fetchall()

    coverage_cursor = await app.state.db.execute(
        f"""
        SELECT
          COUNT(*)::int AS total_matching,
          COUNT(*) FILTER (WHERE p.primary_geometry IS NOT NULL)::int AS mapped_matching
        FROM project p
        WHERE true
        {time_filter}
        {type_filter}
        """,
        scope_params,
    )
    coverage = await coverage_cursor.fetchone()
    total_matching = int(coverage["total_matching"] if coverage else 0)
    mapped_matching = int(coverage["mapped_matching"] if coverage else 0)

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": str(row["id"]),
                "geometry": row["geometry"],
                "properties": {
                    "id": str(row["id"]),
                    "name": row["canonical_name"],
                    "project_type": row["project_type"],
                    "delivery_stage": row["delivery_stage"],
                    "importance_score": float(row["importance_score"] or 0),
                    "source_count": int(row["source_count"] or 0),
                    "display_priority": _display_priority(row),
                    "last_activity_at": (
                        row["last_activity_at"].isoformat() if row["last_activity_at"] else None
                    ),
                },
            }
            for row in rows
        ],
        "metadata": {
            "visible_mapped": len(rows),
            "mapped_matching": mapped_matching,
            "location_pending": max(total_matching - mapped_matching, 0),
            "total_matching": total_matching,
            "time_window": time_window,
            "project_type": project_type,
        },
    }


@app.get("/projects")
async def project_catalog(
    time_window: Annotated[TimeWindow, Query(alias="window")] = "all",
    project_type: Annotated[str | None, Query(max_length=80)] = None,
) -> list[dict]:
    time_filter, type_filter, params = _project_scope(time_window, project_type)
    cursor = await app.state.db.execute(
        f"""
        SELECT
          p.id,
          p.canonical_name,
          p.project_type,
          p.last_activity_at,
          p.importance_score,
          (p.primary_geometry IS NOT NULL) AS has_geometry,
          MAX(psd.value) FILTER (WHERE psd.dimension = 'delivery_stage') AS delivery_stage
        FROM project p
        LEFT JOIN project_status_dimension psd ON psd.project_id = p.id
        WHERE true
        {time_filter}
        {type_filter}
        GROUP BY p.id
        ORDER BY p.importance_score DESC, p.last_activity_at DESC NULLS LAST, p.canonical_name
        """,
        params,
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": str(row["id"]),
            "name": row["canonical_name"],
            "project_type": row["project_type"],
            "last_activity_at": (
                row["last_activity_at"].isoformat() if row["last_activity_at"] else None
            ),
            "importance_score": float(row["importance_score"] or 0),
            "has_geometry": bool(row["has_geometry"]),
            "delivery_stage": row["delivery_stage"],
        }
        for row in rows
    ]


@app.get("/changes")
async def changes(
    time_window: Annotated[TimeWindow, Query(alias="window")] = "week",
    limit: Annotated[int, Query(ge=1, le=250)] = 50,
    project_type: Annotated[str | None, Query(max_length=80)] = None,
) -> list[dict]:
    now = datetime.now(LOCAL_TIMEZONE)
    if time_window == "today":
        event_after = datetime.combine(now.date(), time.min, tzinfo=LOCAL_TIMEZONE)
    elif time_window == "week":
        event_after = now - timedelta(days=7)
    else:
        event_after = None

    params: dict[str, object] = {"limit": limit}
    date_filter = ""
    if event_after is not None:
        params["event_after"] = event_after
        date_filter = "AND COALESCE(pe.occurred_at, pe.observed_at) >= %(event_after)s"
    elif time_window == "upcoming":
        date_filter = "AND pe.occurred_at > now()"

    type_filter = ""
    if project_type:
        params["project_type"] = project_type
        type_filter = "AND p.project_type = %(project_type)s"

    cursor = await app.state.db.execute(
        f"""
        SELECT
          pe.id, pe.project_id, pe.event_type, pe.occurred_at, pe.observed_at,
          pe.title, pe.summary, pe.significance,
          p.canonical_name AS project_name, p.project_type
        FROM project_event pe
        JOIN project p ON p.id = pe.project_id
        WHERE true
        {date_filter}
        {type_filter}
        ORDER BY pe.significance DESC, COALESCE(pe.occurred_at, pe.observed_at) DESC
        LIMIT %(limit)s
        """,
        params,
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": str(row["id"]),
            "project_id": str(row["project_id"]),
            "project_name": row["project_name"],
            "project_type": row["project_type"],
            "event_type": row["event_type"],
            "occurred_at": row["occurred_at"].isoformat() if row["occurred_at"] else None,
            "observed_at": row["observed_at"].isoformat(),
            "title": row["title"],
            "summary": row["summary"],
            "significance": row["significance"],
        }
        for row in rows
    ]


@app.get("/search/projects")
async def search_projects(
    q: Annotated[str, Query(min_length=2, max_length=120)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[dict]:
    needle = q.strip()
    cursor = await app.state.db.execute(
        """
        WITH candidates AS (
          SELECT p.id, 1 AS rank, 'name'::text AS matched_on
          FROM project p
          WHERE p.canonical_name ILIKE '%%' || %(needle)s || '%%'

          UNION ALL

          SELECT pa.project_id, 2, 'alias'
          FROM project_alias pa
          WHERE pa.alias ILIKE '%%' || %(needle)s || '%%'

          UNION ALL

          SELECT a.project_id, 3, a.field
          FROM assertion a
          WHERE a.value #>> '{}' ILIKE '%%' || %(needle)s || '%%'
        ),
        ranked AS (
          SELECT id, MIN(rank) AS rank, MIN(matched_on) AS matched_on
          FROM candidates
          GROUP BY id
        )
        SELECT
          p.id, p.canonical_name, p.project_type, p.summary_cache,
          p.importance_score, p.last_activity_at,
          ST_AsGeoJSON(p.primary_geometry)::json AS geometry,
          ranked.matched_on,
          COALESCE(
            (SELECT jsonb_object_agg(dimension, value)
             FROM project_status_dimension psd WHERE psd.project_id = p.id),
            '{}'::jsonb
          ) AS statuses
        FROM ranked
        JOIN project p ON p.id = ranked.id
        ORDER BY ranked.rank, p.importance_score DESC, p.last_activity_at DESC NULLS LAST
        LIMIT %(limit)s
        """,
        {"needle": needle, "limit": limit},
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": str(row["id"]),
            "name": row["canonical_name"],
            "project_type": row["project_type"],
            "geometry": row["geometry"],
            "statuses": row["statuses"],
            "summary": row["summary_cache"],
            "matched_on": row["matched_on"],
        }
        for row in rows
    ]


@app.get("/projects/{project_id}")
async def project_detail(project_id: UUID) -> dict:
    cursor = await app.state.db.execute(
        """
        SELECT p.id, p.canonical_name, p.project_type,
               ST_AsGeoJSON(p.primary_geometry)::json AS geometry,
               p.summary_cache,
               p.importance_score,
               p.last_activity_at
        FROM project p
        WHERE p.id = %s
        """,
        (project_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")

    location_cursor = await app.state.db.execute(
        """
        SELECT geometry_method, geometry_source, location_accuracy,
               accuracy_meters, geometry_confidence, metadata
        FROM project_location
        WHERE project_id = %s AND is_primary = true
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (project_id,),
    )
    location = await location_cursor.fetchone()

    status_cursor = await app.state.db.execute(
        """
        SELECT dimension, value
        FROM project_status_dimension
        WHERE project_id = %s
        ORDER BY dimension
        """,
        (project_id,),
    )
    statuses = await status_cursor.fetchall()

    assertion_cursor = await app.state.db.execute(
        """
        SELECT a.field, a.value, a.authority_type, a.confidence,
               a.observed_at, sr.canonical_url AS source_url
        FROM assertion a
        LEFT JOIN source_record sr ON sr.id = a.source_record_id
        WHERE a.project_id = %s
        ORDER BY a.observed_at DESC, a.confidence DESC
        """,
        (project_id,),
    )
    assertions = await assertion_cursor.fetchall()

    source_cursor = await app.state.db.execute(
        """
        SELECT s.source_key, s.name AS source_name,
               psr.relationship_type, psr.confidence, psr.evidence,
               sr.canonical_url AS url
        FROM project_source_record psr
        JOIN source_record sr ON sr.id = psr.source_record_id
        JOIN source s ON s.id = sr.source_id
        WHERE psr.project_id = %s
        ORDER BY psr.confidence DESC, s.name
        """,
        (project_id,),
    )
    sources = await source_cursor.fetchall()

    return {
        "id": str(row["id"]),
        "name": row["canonical_name"],
        "project_type": row["project_type"],
        "geometry": row["geometry"],
        "summary": row["summary_cache"],
        "importance_score": float(row["importance_score"] or 0),
        "last_activity_at": row["last_activity_at"].isoformat() if row["last_activity_at"] else None,
        "location": (
            {
                "method": location["geometry_method"],
                "source": location["geometry_source"],
                "accuracy": location["location_accuracy"],
                "accuracy_meters": location["accuracy_meters"],
                "confidence": (
                    float(location["geometry_confidence"])
                    if location["geometry_confidence"] is not None
                    else None
                ),
                "metadata": location["metadata"],
            }
            if location
            else None
        ),
        "statuses": {status["dimension"]: status["value"] for status in statuses},
        "assertions": [
            {
                "field": assertion["field"],
                "value": assertion["value"],
                "authority_type": assertion["authority_type"],
                "confidence": float(assertion["confidence"]),
                "source_url": assertion["source_url"],
                "observed_at": assertion["observed_at"].isoformat(),
            }
            for assertion in assertions
        ],
        "sources": [
            {
                "source_key": source["source_key"],
                "source_name": source["source_name"],
                "relationship_type": source["relationship_type"],
                "confidence": float(source["confidence"]),
                "evidence": source["evidence"],
                "url": source["url"],
            }
            for source in sources
        ],
    }


@app.get("/projects/{project_id}/events")
async def project_events(project_id: UUID) -> list[dict]:
    cursor = await app.state.db.execute(
        """
        SELECT id, event_type, occurred_at, observed_at, title, summary, significance, metadata
        FROM project_event
        WHERE project_id = %s
        ORDER BY COALESCE(occurred_at, observed_at) DESC
        """,
        (project_id,),
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": str(row["id"]),
            "event_type": row["event_type"],
            "occurred_at": row["occurred_at"].isoformat() if row["occurred_at"] else None,
            "observed_at": row["observed_at"].isoformat(),
            "title": row["title"],
            "summary": row["summary"],
            "significance": float(row["significance"] or 0),
            "metadata": row["metadata"],
        }
        for row in rows
    ]
