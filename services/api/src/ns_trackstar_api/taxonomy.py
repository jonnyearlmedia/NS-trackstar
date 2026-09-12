from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

router = APIRouter()
SEMANTIC_FIELDS = ("source_project_type", "record_type", "application_type")


@router.get("/admin/taxonomy/source-project-types")
async def source_project_type_audit(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict:
    """Summarize official semantic subtype assertions for consumer-taxonomy QA.

    This endpoint is intentionally descriptive rather than prescriptive. It exposes
    source vocabulary already stored in Trackstar assertions so consumer categories
    can be normalized from evidence instead of guessed from project names.
    """

    cursor = await request.app.state.db.execute(
        """
        WITH semantic_assertions AS (
          SELECT
            a.project_id,
            a.field,
            a.value #>> '{}' AS source_value,
            a.source_id,
            a.observed_at
          FROM assertion a
          WHERE a.field = ANY(%(semantic_fields)s)
            AND a.value IS NOT NULL
            AND btrim(a.value #>> '{}') <> ''
        ),
        semantic_projects AS (
          SELECT
            p.id,
            p.project_type,
            p.canonical_name,
            sa.field,
            sa.source_value,
            s.source_key,
            ROW_NUMBER() OVER (
              PARTITION BY p.id, sa.field, sa.source_value, s.source_key
              ORDER BY sa.observed_at DESC
            ) AS project_row
          FROM semantic_assertions sa
          JOIN project p ON p.id = sa.project_id
          JOIN source s ON s.id = sa.source_id
        )
        SELECT
          project_type,
          field,
          source_value,
          source_key,
          COUNT(*)::int AS project_count,
          MIN(canonical_name) AS example_project
        FROM semantic_projects
        WHERE project_row = 1
        GROUP BY project_type, field, source_value, source_key
        ORDER BY project_count DESC, field, source_value, source_key
        LIMIT %(limit)s
        """,
        {
            "semantic_fields": list(SEMANTIC_FIELDS),
            "limit": limit,
        },
    )
    rows = await cursor.fetchall()

    totals_cursor = await request.app.state.db.execute(
        """
        SELECT project_type, COUNT(*)::int AS project_count
        FROM project
        GROUP BY project_type
        ORDER BY project_count DESC, project_type
        """
    )
    totals = await totals_cursor.fetchall()

    return {
        "items": [
            {
                "project_type": row["project_type"],
                "field": row["field"],
                "source_value": row["source_value"],
                "source_key": row["source_key"],
                "project_count": int(row["project_count"]),
                "example_project": row["example_project"],
            }
            for row in rows
        ],
        "project_type_totals": [
            {
                "project_type": row["project_type"],
                "project_count": int(row["project_count"]),
            }
            for row in totals
        ],
        "metadata": {
            "purpose": "consumer taxonomy QA",
            "semantic_fields": list(SEMANTIC_FIELDS),
            "note": "Raw official source vocabulary; not a consumer category mapping.",
        },
    }
