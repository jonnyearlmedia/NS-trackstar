from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    app.state.db = await psycopg.AsyncConnection.connect(database_url, row_factory=dict_row)
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
    west: float | None = Query(default=None),
    south: float | None = Query(default=None),
    east: float | None = Query(default=None),
    north: float | None = Query(default=None),
) -> dict:
    params: dict[str, float] = {}
    bbox_filter = ""
    if all(value is not None for value in (west, south, east, north)):
        params = {
            "west": float(west),
            "south": float(south),
            "east": float(east),
            "north": float(north),
        }
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
          ST_AsGeoJSON(p.primary_geometry)::json AS geometry,
          MAX(psd.value) FILTER (WHERE psd.dimension = 'delivery_stage') AS delivery_stage
        FROM project p
        LEFT JOIN project_status_dimension psd ON psd.project_id = p.id
        WHERE p.primary_geometry IS NOT NULL
        {bbox_filter}
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
          ) AS assertions
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
        "statuses": row["statuses"],
        "assertions": row["assertions"],
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
