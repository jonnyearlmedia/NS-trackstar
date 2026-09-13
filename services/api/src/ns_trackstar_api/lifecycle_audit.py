from __future__ import annotations

from collections import Counter, defaultdict
from typing import Annotated

from fastapi import APIRouter, Query, Request

from ns_trackstar_api.area import normalize_lifecycle

router = APIRouter()


@router.get("/admin/lifecycle/audit")
async def lifecycle_audit(
    request: Request,
    sample_limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict:
    """Audit how raw official status dimensions collapse into consumer lifecycle buckets."""

    cursor = await request.app.state.db.execute(
        """
        SELECT
          p.id,
          p.canonical_name,
          p.project_type,
          psd.dimension,
          psd.value
        FROM project p
        LEFT JOIN project_status_dimension psd ON psd.project_id = p.id
        ORDER BY p.id, psd.dimension
        """
    )
    rows = await cursor.fetchall()

    projects: dict[object, dict] = {}
    raw_counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        project = projects.setdefault(
            row["id"],
            {
                "id": str(row["id"]),
                "name": row["canonical_name"],
                "project_type": row["project_type"],
                "statuses": {},
            },
        )
        if row["dimension"] and row["value"]:
            dimension = str(row["dimension"])
            value = str(row["value"])
            project["statuses"][dimension] = value
            raw_counts[(dimension, value)] += 1

    stage_counts: Counter[str] = Counter()
    stage_examples: dict[str, list[dict]] = defaultdict(list)
    unknown_raw_counts: Counter[tuple[str, str]] = Counter()

    for project in projects.values():
        stage, matched_dimension, matched_value = normalize_lifecycle(project["statuses"])
        stage_counts[stage] += 1
        if len(stage_examples[stage]) < sample_limit:
            stage_examples[stage].append(
                {
                    "id": project["id"],
                    "name": project["name"],
                    "project_type": project["project_type"],
                    "statuses": project["statuses"],
                    "matched_dimension": matched_dimension,
                    "matched_value": matched_value,
                }
            )
        if stage == "unknown":
            for dimension, value in project["statuses"].items():
                unknown_raw_counts[(dimension, value)] += 1

    return {
        "stage_counts": dict(stage_counts),
        "stage_examples": dict(stage_examples),
        "raw_statuses": [
            {"dimension": dimension, "value": value, "project_count": count}
            for (dimension, value), count in raw_counts.most_common()
        ],
        "unknown_raw_statuses": [
            {"dimension": dimension, "value": value, "project_count": count}
            for (dimension, value), count in unknown_raw_counts.most_common()
        ],
        "metadata": {
            "project_count": len(projects),
            "sample_limit_per_stage": sample_limit,
            "note": (
                "Audit only. Unknown is intentionally valid when official wording does not "
                "prove one consumer lifecycle state."
            ),
        },
    }
