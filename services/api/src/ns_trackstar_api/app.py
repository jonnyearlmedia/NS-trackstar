from __future__ import annotations

import os
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
SEARCH_ASSERTION_FIELDS = (
    "address",
    "apn",
    "business_name",
    "description",
    "location_description",
    "owner_applicant",
    "permit_number",
    "planning_case",
    "project_number",
    "road",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    app.state.db = await psycopg.AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
        autocommit=True,
    )
    try:
        yield
    finally:
        await app.state.db.close()


app = FastAPI(title="NS Trackstar API", version="0.1.0", lifespan=lifespan)

origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _time_window_sql(time_window: TimeWindow) -> tuple[str, dict[str, object]]:
    now = datetime.now(LOCAL_TIMEZONE)
    if time_window == "today":
        return (
            "AND p.last_activity_at >= %(activity_after)s",
            {"activity_after": datetime.combine(now.date(), time.min, tzinfo=LOCAL_TIMEZONE)},
        )
    if time_window == "week":
        return "AND p.last_activity_at >= %(activity_after)s", {
            "activity_after": now - timedelta(days=7)
        }
    if time_window == "upcoming":
        return (
            """
            AND NOT EXISTS (
              SELECT 1
              FROM project_status_dimension upcoming_status
              WHERE upcoming_status.project_id = p.id
                AND upcoming_status.dimension = 'delivery_stage'
                AND lower(upcoming_status.value) IN (
                  'completed', 'complete', 'closed', 'construction',
                  'under construction', 'cancelled', 'canceled'
                )
            )
            """,
            {},
        )
    return "", {}


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
) -> dict:
    params: dict[str, object] = {}
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

    time_filter, time_params = _time_window_sql(time_window)
    params.update(time_params)

    cursor = await app.state.db.execute(
        f"""
        SELECT
          p.id,
          p.canonical_name,
          p.project_type,
          p.last_activity_at,
          ST_AsGeoJSON(p.primary_geometry)::json AS geometry,
          MAX(psd.value) FILTER (WHERE psd.dimension = 'delivery_stage') AS delivery_stage
        FROM project p
        LEFT JOIN project_status_dimension psd ON psd.project_id = p.id
        WHERE p.primary_geometry IS NOT NULL
        {bbox_filter}
        {time_filter}
        GROUP BY p.id
        ORDER BY p.last_activity_at DESC NULLS LAST
        LIMIT 1000
        """,
        params,
    )
    rows = await cursor.fetchall()
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
                    "last_activity_at": (
                        row["last_activity_at"].isoformat() if row["last_activity_at"] else None
                    ),
                },
            }
            for row in rows
        ],
    }


@app.get("/changes")
async def changes(
    time_window: Annotated[TimeWindow, Query(alias="window")] = "week",
    limit: Annotated[int, Query(ge=1, le=250)] = 50,
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
        ORDER BY COALESCE(pe.occurred_at, pe.observed_at) DESC, pe.significance DESC
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
    q: Annotated[str, Query(min_length=2, max_length=160)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[dict]:
    query = " ".join(q.split())
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search query is too short")
    pattern = f"%{query}%"
    params = {
        "query": query,
        "pattern": pattern,
        "limit": limit,
        "assertion_fields": list(SEARCH_ASSERTION_FIELDS),
    }

    cursor = await app.state.db.execute(
        """
        SELECT
          p.id, p.canonical_name, p.project_type, p.last_activity_at,
          ST_AsGeoJSON(p.primary_geometry)::json AS geometry,
          COALESCE(
            (SELECT jsonb_object_agg(dimension, value)
             FROM project_status_dimension WHERE project_id = p.id),
            '{}'::jsonb
          ) AS statuses,
          COALESCE(
            p.summary_cache,
            (SELECT a.value #>> '{}'
             FROM assertion a
             WHERE a.project_id = p.id AND a.field = 'description'
             ORDER BY a.observed_at DESC LIMIT 1)
          ) AS summary,
          CASE
            WHEN lower(p.canonical_name) = lower(%(query)s) THEN 100
            WHEN p.canonical_name ILIKE %(pattern)s THEN 90
            WHEN EXISTS (
              SELECT 1 FROM project_alias pa
              WHERE pa.project_id = p.id AND lower(pa.alias::text) = lower(%(query)s)
            ) THEN 85
            WHEN EXISTS (
              SELECT 1 FROM project_alias pa
              WHERE pa.project_id = p.id AND pa.alias::text ILIKE %(pattern)s
            ) THEN 80
            WHEN EXISTS (
              SELECT 1 FROM assertion a
              WHERE a.project_id = p.id
                AND a.field = ANY(%(assertion_fields)s)
                AND jsonb_typeof(a.value) = 'string'
                AND (a.value #>> '{}') ILIKE %(pattern)s
            ) THEN 70
            ELSE 60
          END AS match_score,
          CASE
            WHEN p.canonical_name ILIKE %(pattern)s THEN 'project_name'
            WHEN EXISTS (
              SELECT 1 FROM project_alias pa
              WHERE pa.project_id = p.id AND pa.alias::text ILIKE %(pattern)s
            ) THEN 'alias'
            WHEN EXISTS (
              SELECT 1 FROM assertion a
              WHERE a.project_id = p.id
                AND a.field = ANY(%(assertion_fields)s)
                AND jsonb_typeof(a.value) = 'string'
                AND (a.value #>> '{}') ILIKE %(pattern)s
            ) THEN 'project_evidence'
            ELSE 'source_record'
          END AS matched_on
        FROM project p
        WHERE
          p.canonical_name ILIKE %(pattern)s
          OR EXISTS (
            SELECT 1 FROM project_alias pa
            WHERE pa.project_id = p.id AND pa.alias::text ILIKE %(pattern)s
          )
          OR EXISTS (
            SELECT 1 FROM assertion a
            WHERE a.project_id = p.id
              AND a.field = ANY(%(assertion_fields)s)
              AND jsonb_typeof(a.value) = 'string'
              AND (a.value #>> '{}') ILIKE %(pattern)s
          )
          OR EXISTS (
            SELECT 1
            FROM project_source_record psr
            JOIN source_record sr ON sr.id = psr.source_record_id
            WHERE psr.project_id = p.id
              AND concat_ws(
                ' ', sr.normalized_payload ->> 'record_number',
                sr.normalized_payload ->> 'name', sr.normalized_payload ->> 'address',
                sr.normalized_payload ->> 'apn', sr.normalized_payload ->> 'description'
              ) ILIKE %(pattern)s
          )
        ORDER BY match_score DESC, p.last_activity_at DESC NULLS LAST, p.canonical_name
        LIMIT %(limit)s
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
            "geometry": row["geometry"],
            "statuses": row["statuses"],
            "summary": row["summary"],
            "matched_on": row["matched_on"],
        }
        for row in rows
    ]


@app.get("/projects/{project_id}")
async def project_detail(project_id: UUID) -> dict:
    cursor = await app.state.db.execute(
        """
        SELECT
          p.id, p.canonical_name, p.project_type, p.last_activity_at,
          ST_AsGeoJSON(p.primary_geometry)::json AS geometry,
          COALESCE(
            (SELECT jsonb_object_agg(dimension, value)
             FROM project_status_dimension WHERE project_id = p.id),
            '{}'::jsonb
          ) AS statuses,
          COALESCE(
            (SELECT jsonb_agg(jsonb_build_object(
              'field', a.field,
              'value', a.value,
              'authority_type', a.authority_type,
              'confidence', a.confidence,
              'observed_at', a.observed_at,
              'source_url', COALESCE(a.source_url, sr.canonical_url)
            ) ORDER BY a.observed_at DESC)
             FROM assertion a
             LEFT JOIN source_record sr ON sr.id = a.source_record_id
             WHERE a.project_id = p.id),
            '[]'::jsonb
          ) AS assertions,
          (SELECT jsonb_build_object(
             'method', pl.geometry_method,
             'source', pl.geometry_source,
             'accuracy', pl.location_accuracy,
             'accuracy_meters', pl.geometry_accuracy_meters,
             'confidence', pl.geometry_confidence
           )
           FROM project_location pl
           WHERE pl.project_id = p.id AND pl.is_primary
           LIMIT 1) AS location,
          COALESCE(
            (SELECT jsonb_agg(jsonb_build_object(
              'source_key', s.source_key,
              'source_name', s.name,
              'relationship_type', psr.relationship_type,
              'confidence', psr.confidence,
              'evidence', psr.evidence,
              'url', sr.canonical_url
            ) ORDER BY s.name, sr.external_id)
             FROM project_source_record psr
             JOIN source_record sr ON sr.id = psr.source_record_id
             JOIN source s ON s.id = sr.source_id
             WHERE psr.project_id = p.id),
            '[]'::jsonb
          ) AS sources
        FROM project p
        WHERE p.id = %s
        """,
        (project_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "id": str(row["id"]),
        "name": row["canonical_name"],
        "project_type": row["project_type"],
        "last_activity_at": (
            row["last_activity_at"].isoformat() if row["last_activity_at"] else None
        ),
        "geometry": row["geometry"],
        "location": row["location"],
        "statuses": row["statuses"],
        "assertions": row["assertions"],
        "sources": row["sources"],
    }


@app.get("/projects/{project_id}/events")
async def project_events(project_id: UUID) -> list[dict]:
    cursor = await app.state.db.execute(
        """
        SELECT id, event_type, occurred_at, observed_at, title, summary, significance, metadata
        FROM project_event
        WHERE project_id = %s
        ORDER BY COALESCE(occurred_at, observed_at) DESC
        LIMIT 250
        """,
        (project_id,),
    )
    rows = await cursor.fetchall()
    return [
        {
            **{
                key: value
                for key, value in row.items()
                if key not in {"id", "occurred_at", "observed_at"}
            },
            "id": str(row["id"]),
            "occurred_at": row["occurred_at"].isoformat() if row["occurred_at"] else None,
            "observed_at": row["observed_at"].isoformat(),
        }
        for row in rows
    ]
