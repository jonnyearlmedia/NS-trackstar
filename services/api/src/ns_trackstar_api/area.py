from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request

router = APIRouter()
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")
AreaWindow = Literal["today", "week", "upcoming", "all"]
LifecycleStage = Literal["review", "approved", "construction", "completed", "inactive", "unknown"]

INACTIVE_TERMS = (
    "canceled",
    "cancelled",
    "withdrawn",
    "denied",
    "rejected",
    "abandoned",
    "stalled",
    "inactive",
)
COMPLETED_TERMS = (
    "completed",
    "complete",
    "closed",
    "finished",
)
CONSTRUCTION_TERMS = (
    "under construction",
    "active construction",
    "in construction",
    "construction underway",
    "construction phase",
)
APPROVED_TERMS = (
    "approved",
    "entitled",
    "permit issued",
    "permits issued",
)
REVIEW_TERMS = (
    "under review",
    "in review",
    "pending review",
    "application submitted",
    "submitted",
    "processing",
    "environmental review",
    "planning review",
)


def _normalized(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def normalize_lifecycle(statuses: dict[str, str]) -> tuple[LifecycleStage, str | None, str | None]:
    """Conservatively normalize heterogeneous official status labels.

    Trackstar only emits a consumer lifecycle bucket when a current source status is
    explicit enough to support it. Ambiguous labels remain ``unknown`` instead of being
    promoted into a more specific stage.
    """

    normalized = [
        (dimension, value, _normalized(value))
        for dimension, value in statuses.items()
        if value is not None and str(value).strip()
    ]

    def exact_or_phrase(terms: tuple[str, ...]) -> tuple[str | None, str | None]:
        for dimension, raw_value, value in normalized:
            if any(value == term or term in value for term in terms):
                return dimension, raw_value
        return None, None

    dimension, value = exact_or_phrase(INACTIVE_TERMS)
    if dimension:
        return "inactive", dimension, value

    dimension, value = exact_or_phrase(COMPLETED_TERMS)
    if dimension:
        return "completed", dimension, value

    for dimension, raw_value, value in normalized:
        if "pre construction" in value:
            continue
        if value == "construction" or any(term in value for term in CONSTRUCTION_TERMS):
            return "construction", dimension, raw_value

    dimension, value = exact_or_phrase(APPROVED_TERMS)
    if dimension:
        return "approved", dimension, value

    dimension, value = exact_or_phrase(REVIEW_TERMS)
    if dimension:
        return "review", dimension, value

    # Dimension names can be informative, but only when the value itself indicates an
    # active/pending workflow. This avoids calling every project with a planning field
    # "under review" after it has already advanced to another stage.
    for dimension, raw_value, value in normalized:
        dimension_name = _normalized(dimension)
        if dimension_name in {"planning", "entitlement", "environmental", "building permit"}:
            if value in {"pending", "active", "open", "current"}:
                return "review", dimension, raw_value

    return "unknown", None, None


def _event_after(window: AreaWindow) -> datetime | None:
    now = datetime.now(LOCAL_TIMEZONE)
    if window == "today":
        return datetime.combine(now.date(), time.min, tzinfo=LOCAL_TIMEZONE)
    if window == "week":
        return now - timedelta(days=7)
    return None


def _bbox_params(west: float, south: float, east: float, north: float) -> dict[str, float]:
    # FastAPI range validation handles world bounds. Normalize crossed values to fail
    # closed: a malformed viewport should return zero rows rather than accidentally
    # expanding to a global query.
    if west >= east or south >= north:
        return {"west": 0.0, "south": 0.0, "east": 0.0, "north": 0.0}
    return {"west": west, "south": south, "east": east, "north": north}


@router.get("/map/lifecycle-truth")
async def lifecycle_truth(
    request: Request,
    west: Annotated[float, Query(ge=-180, le=180)],
    south: Annotated[float, Query(ge=-90, le=90)],
    east: Annotated[float, Query(ge=-180, le=180)],
    north: Annotated[float, Query(ge=-90, le=90)],
) -> list[dict]:
    params = _bbox_params(west, south, east, north)
    cursor = await request.app.state.db.execute(
        """
        SELECT p.id, psd.dimension, psd.value
        FROM project p
        LEFT JOIN project_status_dimension psd ON psd.project_id = p.id
        WHERE p.primary_geometry IS NOT NULL
          AND p.primary_geometry && ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)
        ORDER BY p.id, psd.dimension
        """,
        params,
    )
    rows = await cursor.fetchall()
    grouped: dict[object, dict[str, str]] = defaultdict(dict)
    for row in rows:
        if row["dimension"] and row["value"]:
            grouped[row["id"]][str(row["dimension"])] = str(row["value"])
        else:
            grouped[row["id"]]

    response: list[dict] = []
    for project_id, statuses in grouped.items():
        stage, matched_dimension, matched_value = normalize_lifecycle(statuses)
        response.append(
            {
                "id": str(project_id),
                "lifecycle_stage": stage,
                "matched_dimension": matched_dimension,
                "matched_value": matched_value,
                "statuses": statuses,
            }
        )
    return response


@router.get("/area/changes")
async def area_changes(
    request: Request,
    west: Annotated[float, Query(ge=-180, le=180)],
    south: Annotated[float, Query(ge=-90, le=90)],
    east: Annotated[float, Query(ge=-180, le=180)],
    north: Annotated[float, Query(ge=-90, le=90)],
    window: Annotated[AreaWindow, Query()] = "week",
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    include_reviews: Annotated[bool, Query()] = False,
) -> dict:
    params: dict[str, object] = _bbox_params(west, south, east, north)
    params["query_limit"] = limit + 1
    date_filter = ""
    event_after = _event_after(window)
    if event_after is not None:
        params["event_after"] = event_after
        date_filter = "AND COALESCE(pe.occurred_at, pe.observed_at) >= %(event_after)s"
    elif window == "upcoming":
        date_filter = "AND pe.occurred_at > now()"

    review_filter = "" if include_reviews else "AND p.project_type <> 'environmental_review'"
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
        WHERE p.primary_geometry IS NOT NULL
          AND p.primary_geometry && ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)
          {date_filter}
          {review_filter}
          AND (pe.event_type <> 'project_discovered' OR COALESCE(pe.significance, 0) > 0.5)
        ORDER BY COALESCE(pe.significance, 0) DESC,
                 COALESCE(pe.occurred_at, pe.observed_at) DESC,
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
            "bounds": {"west": west, "south": south, "east": east, "north": north},
        },
    }


@router.get("/area/briefing")
async def area_briefing(
    request: Request,
    west: Annotated[float, Query(ge=-180, le=180)],
    south: Annotated[float, Query(ge=-90, le=90)],
    east: Annotated[float, Query(ge=-180, le=180)],
    north: Annotated[float, Query(ge=-90, le=90)],
    window: Annotated[AreaWindow, Query()] = "week",
    limit: Annotated[int, Query(ge=2, le=8)] = 5,
    include_reviews: Annotated[bool, Query()] = False,
) -> list[dict]:
    params: dict[str, object] = _bbox_params(west, south, east, north)
    params["limit"] = limit
    review_filter = "" if include_reviews else "AND p.project_type <> 'environmental_review'"
    event_filter = ""
    event_after = _event_after(window)
    if event_after is not None:
        params["event_after"] = event_after
        event_filter = "AND COALESCE(le.occurred_at, le.observed_at) >= %(event_after)s"
    elif window == "upcoming":
        event_filter = "AND le.occurred_at > now()"

    cursor = await request.app.state.db.execute(
        f"""
        WITH latest_event AS (
          SELECT DISTINCT ON (pe.project_id)
            pe.project_id,
            pe.id,
            pe.title,
            pe.summary,
            pe.event_type,
            pe.occurred_at,
            pe.observed_at,
            pe.significance
          FROM project_event pe
          WHERE pe.event_type <> 'project_discovered' OR COALESCE(pe.significance, 0) > 0.5
          ORDER BY pe.project_id, COALESCE(pe.occurred_at, pe.observed_at) DESC
        ),
        source_counts AS (
          SELECT psr.project_id, COUNT(DISTINCT psr.source_record_id)::int AS source_count
          FROM project_source_record psr
          GROUP BY psr.project_id
        )
        SELECT
          p.id,
          p.canonical_name,
          p.project_type,
          p.last_activity_at,
          p.importance_score,
          ST_AsGeoJSON(p.primary_geometry)::json AS geometry,
          COALESCE(
            (SELECT jsonb_object_agg(dimension, value)
             FROM project_status_dimension psd
             WHERE psd.project_id = p.id),
            '{{}}'::jsonb
          ) AS statuses,
          COALESCE(
            p.summary_cache,
            (SELECT a.value #>> '{{}}'
             FROM assertion a
             WHERE a.project_id = p.id AND a.field = 'description'
             ORDER BY a.observed_at DESC LIMIT 1)
          ) AS project_summary,
          COALESCE(sc.source_count, 0) AS source_count,
          le.id AS event_id,
          le.title AS event_title,
          le.summary AS event_summary,
          le.event_type,
          le.occurred_at,
          le.observed_at,
          COALESCE(le.significance, 0) AS event_significance,
          (
            LEAST(1, GREATEST(0, COALESCE(p.importance_score, 0))) * 0.50
            + COALESCE(le.significance, 0) * 0.35
            + LEAST(COALESCE(sc.source_count, 0), 5) / 5.0 * 0.15
          ) AS briefing_score
        FROM project p
        LEFT JOIN latest_event le ON le.project_id = p.id
        LEFT JOIN source_counts sc ON sc.project_id = p.id
        WHERE p.primary_geometry IS NOT NULL
          AND p.primary_geometry && ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)
          {review_filter}
          {event_filter}
        ORDER BY briefing_score DESC, p.last_activity_at DESC NULLS LAST, p.canonical_name
        LIMIT %(limit)s
        """,
        params,
    )
    rows = await cursor.fetchall()

    response: list[dict] = []
    for row in rows:
        lifecycle_stage, matched_dimension, matched_value = normalize_lifecycle(row["statuses"] or {})
        event = None
        if row["event_id"]:
            event = {
                "id": str(row["event_id"]),
                "title": row["event_title"],
                "summary": row["event_summary"],
                "event_type": row["event_type"],
                "occurred_at": row["occurred_at"].isoformat() if row["occurred_at"] else None,
                "observed_at": row["observed_at"].isoformat() if row["observed_at"] else None,
                "significance": float(row["event_significance"] or 0),
            }
        response.append(
            {
                "id": str(row["id"]),
                "name": row["canonical_name"],
                "project_type": row["project_type"],
                "last_activity_at": row["last_activity_at"].isoformat() if row["last_activity_at"] else None,
                "importance_score": float(row["importance_score"] or 0),
                "briefing_score": float(row["briefing_score"] or 0),
                "geometry": row["geometry"],
                "statuses": row["statuses"],
                "summary": row["project_summary"],
                "source_count": int(row["source_count"] or 0),
                "lifecycle_stage": lifecycle_stage,
                "lifecycle_evidence": {
                    "dimension": matched_dimension,
                    "value": matched_value,
                },
                "event": event,
            }
        )
    return response
