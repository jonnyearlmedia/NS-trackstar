from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from ns_trackstar_api.area import normalize_lifecycle
from ns_trackstar_api.categories import SEMANTIC_FIELDS, normalize_consumer_category

router = APIRouter()
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


@router.get("/search/projects/classified")
async def search_projects_classified(
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=160)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[dict]:
    """Search projects with the same consumer classification used by the map/detail UI.

    Ranking intentionally mirrors the established `/search/projects` ordering. This
    route only enriches each result with canonical consumer category/lifecycle truth so
    search does not briefly show heuristic labels before project detail loads.
    """

    query = " ".join(q.split())
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search query is too short")

    pattern = f"%{query}%"
    params = {
        "query": query,
        "pattern": pattern,
        "limit": limit,
        "assertion_fields": list(SEARCH_ASSERTION_FIELDS),
        "semantic_fields": list(SEMANTIC_FIELDS),
    }
    cursor = await request.app.state.db.execute(
        """
        SELECT
          p.id,
          p.canonical_name,
          p.project_type,
          p.last_activity_at,
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
          COALESCE(
            (SELECT jsonb_agg(DISTINCT a.value #>> '{}')
             FROM assertion a
             WHERE a.project_id = p.id
               AND a.field = ANY(%(semantic_fields)s)
               AND jsonb_typeof(a.value) = 'string'),
            '[]'::jsonb
          ) AS semantic_values,
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

    results: list[dict] = []
    for row in rows:
        semantic_values = [str(value) for value in (row["semantic_values"] or []) if value]
        category, category_basis, category_evidence = normalize_consumer_category(
            project_type=str(row["project_type"]),
            semantic_values=semantic_values,
            project_name=str(row["canonical_name"]),
        )
        lifecycle_stage, lifecycle_dimension, lifecycle_value = normalize_lifecycle(
            row["statuses"] or {}
        )
        results.append(
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
                "consumer_category": category,
                "category_basis": category_basis,
                "category_evidence": category_evidence,
                "lifecycle_stage": lifecycle_stage,
                "lifecycle_evidence": {
                    "dimension": lifecycle_dimension,
                    "value": lifecycle_value,
                },
            }
        )
    return results
