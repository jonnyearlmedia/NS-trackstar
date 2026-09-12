from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

router = APIRouter()


@router.get("/admin/taxonomy/source-project-types")
async def source_project_type_audit(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
) -> dict:
    """Summarize official source project subtypes for consumer-taxonomy QA.

    This endpoint is intentionally descriptive rather than prescriptive. It exposes
    the source vocabulary already stored in assertions so consumer categories can be
    normalized from evidence instead of guessed from project names.
    """

    cursor = await request.app.state.db.execute(
        """
        WITH subtype_assertions AS (
          SELECT
            a.project_id,
            a.value #>> '{}' AS source_project_type,
            a.source_id,
            a.observed_at
          FROM assertion a
          WHERE a.field = 'source_project_type'
            AND a.value IS NOT NULL
            AND btrim(a.value #>> '{}') <> ''
        ),
        subtype_projects AS (
          SELECT
            p.id,
            p.project_type,
            p.canonical_name,
            sa.source_project_type,
            s.source_key,
            ROW_NUMBER() OVER (
              PARTITION BY p.id, sa.source_project_type, s.source_key
              ORDER BY sa.observed_at DESC
            ) AS project_row
          FROM subtype_assertions sa
          JOIN project p ON p.id = sa.project_id
          JOIN source s ON s.id = sa.source_id
        )
        SELECT
          project_type,
          source_project_type,
          source_key,
          COUNT(*)::int AS project_count,
          MIN(canonical_name) AS example_project
        FROM subtype_projects
        WHERE project_row = 1
        GROUP BY project_type, source_project_type, source_key
        ORDER BY project_count DESC, source_project_type, source_key
        LIMIT %(limit)s
        """,
        {"limit": limit},
    )
    rows = await cursor.fetchall()

    return {
        "items": [
            {
                "project_type": row["project_type"],
                "source_project_type": row["source_project_type"],
                "source_key": row["source_key"],
                "project_count": int(row["project_count"]),
                "example_project": row["example_project"],
            }
            for row in rows
        ],
        "metadata": {
            "purpose": "consumer taxonomy QA",
            "note": "Raw official source subtype vocabulary; not a consumer category mapping.",
        },
    }
