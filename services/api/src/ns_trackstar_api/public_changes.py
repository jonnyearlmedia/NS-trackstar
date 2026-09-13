from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request

router = APIRouter()
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")
AreaWindow = Literal["today", "week", "upcoming", "all"]
SUPPRESSED_PUBLIC_SOURCE_KEYS = ("vallejo.civicclerk",)


def _event_after(window: AreaWindow) -> datetime | None:
    now = datetime.now(LOCAL_TIMEZONE)
    if window == "today":
        return datetime.combine(now.date(), time.min, tzinfo=LOCAL_TIMEZONE)
    if window == "week":
        return now - timedelta(days=7)
    return None


@router.get("/area/changes/public")
async def public_area_changes(
    request: Request,
    west: Annotated[float, Query(ge=-180, le=180)],
    south: Annotated[float, Query(ge=-90, le=90)],
    east: Annotated[float, Query(ge=-180, le=180)],
    north: Annotated[float, Query(ge=-90, le=90)],
    window: Annotated[AreaWindow, Query()] = "week",
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
) -> dict:
    params: dict[str, object] = {
        "west": west,
        "south": south,
        "east": east,
        "north": north,
        "query_limit": limit + 1,
        "suppressed_sources": list(SUPPRESSED_PUBLIC_SOURCE_KEYS),
    }
    date_filter = ""
    event_after = _event_after(window)
    if event_after is not None:
        params["event_after"] = event_after
        date_filter = "AND COALESCE(pe.occurred_at, pe.observed_at) >= %(event_after)s"
    elif window == "upcoming":
        date_filter = "AND pe.occurred_at > now()"

    cursor = await request.app.state.db.execute(
        f"""
        SELECT
          pe.id,
          pe.project_id,
          pe.event_type,
          pe.occurred_at,
          pe.observed_at,
          pe.title,
          pe.summary,
          pe.significance,
          p.canonical_name AS project_name,
          p.project_type
        FROM project_event pe
        JOIN project p ON p.id = pe.project_id
        LEFT JOIN source_record sr ON sr.id = pe.source_record_id
        LEFT JOIN source s ON s.id = sr.source_id
        WHERE p.primary_geometry IS NOT NULL
          AND p.primary_geometry && ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)
          {date_filter}
          AND p.project_type <> 'environmental_review'
          AND (s.source_key IS NULL OR s.source_key <> ALL(%(suppressed_sources)s))
          AND (pe.event_type <> 'project_discovered' OR COALESCE(pe.significance, 0) > 0.5)
        ORDER BY COALESCE(pe.occurred_at, pe.observed_at) DESC,
                 COALESCE(pe.significance, 0) DESC,
                 p.canonical_name
        LIMIT %(query_limit)s
        """,
        params,
    )
    rows = await cursor.fetchall()
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
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
                "significance": float(row["significance"] or 0),
            }
            for row in rows
        ],
        "metadata": {
            "window": window,
            "limit": limit,
            "truncated": truncated,
            "suppressed_source_keys": list(SUPPRESSED_PUBLIC_SOURCE_KEYS),
        },
    }
