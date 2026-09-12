from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")
BriefingWindow = Literal["today", "week", "upcoming", "all"]


def _briefing_window_sql(window: BriefingWindow) -> tuple[str, dict[str, object]]:
    now = datetime.now(LOCAL_TIMEZONE)
    if window == "today":
        return (
            "AND COALESCE(le.occurred_at, le.observed_at, p.last_activity_at) >= %(after)s",
            {"after": datetime.combine(now.date(), time.min, tzinfo=LOCAL_TIMEZONE)},
        )
    if window == "week":
        return (
            "AND COALESCE(le.occurred_at, le.observed_at, p.last_activity_at) >= %(after)s",
            {"after": now - timedelta(days=7)},
        )
    if window == "upcoming":
        return "AND le.occurred_at > now()", {}
    return "", {}


@router.get("/projects/{project_id}/context")
async def project_context(project_id: UUID, request: Request) -> dict:
    project_cursor = await request.app.state.db.execute(
        """
        SELECT
          p.id,
          p.canonical_name,
          p.importance_score,
          p.summary_cache,
          COALESCE(
            (SELECT a.value #>> '{}'
             FROM assertion a
             WHERE a.project_id = p.id AND a.field = 'description'
             ORDER BY a.observed_at DESC LIMIT 1),
            NULL
          ) AS evidence_summary,
          COALESCE(
            (SELECT jsonb_agg(jsonb_build_object(
              'alias', pa.alias,
              'alias_type', pa.alias_type
            ) ORDER BY pa.alias)
             FROM project_alias pa
             WHERE pa.project_id = p.id),
            '[]'::jsonb
          ) AS aliases
        FROM project p
        WHERE p.id = %s
        """,
        (project_id,),
    )
    project = await project_cursor.fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    relationship_cursor = await request.app.state.db.execute(
        """
        SELECT * FROM (
          SELECT
            pr.relationship_type::text AS relationship_type,
            pr.confidence,
            pr.evidence,
            'outgoing'::text AS direction,
            other.id AS project_id,
            other.canonical_name AS project_name,
            other.project_type,
            (other.primary_geometry IS NOT NULL) AS mapped
          FROM project_relationship pr
          JOIN project other ON other.id = pr.to_project_id
          WHERE pr.from_project_id = %s

          UNION ALL

          SELECT
            pr.relationship_type::text AS relationship_type,
            pr.confidence,
            pr.evidence,
            'incoming'::text AS direction,
            other.id AS project_id,
            other.canonical_name AS project_name,
            other.project_type,
            (other.primary_geometry IS NOT NULL) AS mapped
          FROM project_relationship pr
          JOIN project other ON other.id = pr.from_project_id
          WHERE pr.to_project_id = %s
        ) relationships
        ORDER BY confidence DESC, project_name
        """,
        (project_id, project_id),
    )
    relationships = await relationship_cursor.fetchall()

    match_cursor = await request.app.state.db.execute(
        """
        SELECT
          emc.proposed_relationship::text AS proposed_relationship,
          emc.state::text AS state,
          emc.score,
          emc.signals,
          CASE WHEN emc.left_project_id = %s THEN right_project.id ELSE left_project.id END AS project_id,
          CASE WHEN emc.left_project_id = %s THEN right_project.canonical_name ELSE left_project.canonical_name END AS project_name
        FROM entity_match_candidate emc
        JOIN project left_project ON left_project.id = emc.left_project_id
        JOIN project right_project ON right_project.id = emc.right_project_id
        WHERE (emc.left_project_id = %s OR emc.right_project_id = %s)
          AND emc.state IN ('confirmed', 'soft_link')
        ORDER BY emc.score DESC
        LIMIT 20
        """,
        (project_id, project_id, project_id, project_id),
    )
    matches = await match_cursor.fetchall()

    return {
        "id": str(project["id"]),
        "name": project["canonical_name"],
        "importance_score": float(project["importance_score"] or 0),
        "summary": project["summary_cache"] or project["evidence_summary"],
        "aliases": project["aliases"],
        "relationships": [
            {
                **{
                    key: value
                    for key, value in row.items()
                    if key not in {"project_id", "confidence"}
                },
                "project_id": str(row["project_id"]),
                "confidence": float(row["confidence"]),
            }
            for row in relationships
        ],
        "matches": [
            {
                **{
                    key: value
                    for key, value in row.items()
                    if key not in {"project_id", "score"}
                },
                "project_id": str(row["project_id"]),
                "score": float(row["score"]),
            }
            for row in matches
        ],
    }


@router.get("/briefing")
async def briefing(
    request: Request,
    window: Annotated[BriefingWindow, Query()] = "today",
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
    include_reviews: Annotated[bool, Query()] = False,
) -> list[dict]:
    window_filter, params = _briefing_window_sql(window)
    params["limit"] = limit
    consumer_filter = "" if include_reviews else "AND p.project_type <> 'environmental_review'"
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
            LEAST(1, GREATEST(0, COALESCE(p.importance_score, 0))) * 0.45
            + COALESCE(le.significance, 0) * 0.45
            + LEAST(COALESCE(sc.source_count, 0), 5) / 5.0 * 0.10
          ) AS briefing_score
        FROM project p
        LEFT JOIN latest_event le ON le.project_id = p.id
        LEFT JOIN source_counts sc ON sc.project_id = p.id
        WHERE p.primary_geometry IS NOT NULL
        {consumer_filter}
        {window_filter}
          AND (
            COALESCE(sc.source_count, 0) >= 2
            OR COALESCE(p.importance_score, 0) >= 0.2
            OR EXISTS (
              SELECT 1
              FROM project_status_dimension meaningful_status
              WHERE meaningful_status.project_id = p.id
            )
            OR (
              le.event_type IS NOT NULL
              AND le.event_type <> 'project_discovered'
              AND COALESCE(le.significance, 0) >= 0.6
            )
          )
        ORDER BY briefing_score DESC, p.last_activity_at DESC NULLS LAST, p.canonical_name
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
            "last_activity_at": row["last_activity_at"].isoformat() if row["last_activity_at"] else None,
            "importance_score": float(row["importance_score"] or 0),
            "briefing_score": float(row["briefing_score"] or 0),
            "geometry": row["geometry"],
            "statuses": row["statuses"],
            "summary": row["project_summary"],
            "source_count": row["source_count"],
            "event": (
                {
                    "id": str(row["event_id"]),
                    "title": row["event_title"],
                    "summary": row["event_summary"],
                    "event_type": row["event_type"],
                    "occurred_at": row["occurred_at"].isoformat() if row["occurred_at"] else None,
                    "observed_at": row["observed_at"].isoformat() if row["observed_at"] else None,
                    "significance": float(row["event_significance"] or 0),
                }
                if row["event_id"]
                else None
            ),
        }
        for row in rows
    ]
