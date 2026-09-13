from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/admin/quality/audit")
async def quality_audit(request: Request) -> dict:
    """Surface duplicate/conflict/manual-QA risks without auto-merging anything.

    The endpoint is deliberately conservative. It identifies records that deserve review;
    it never treats name similarity or conflicting public assertions as permission to
    rewrite canonical truth automatically.
    """

    duplicates_cursor = await request.app.state.db.execute(
        """
        WITH grouped AS (
          SELECT
            lower(regexp_replace(trim(canonical_name), '\\s+', ' ', 'g')) AS normalized_name,
            COUNT(*)::int AS project_count,
            jsonb_agg(
              jsonb_build_object(
                'id', id,
                'name', canonical_name,
                'project_type', project_type,
                'last_activity_at', last_activity_at
              ) ORDER BY last_activity_at DESC NULLS LAST, id
            ) AS projects
          FROM project
          GROUP BY lower(regexp_replace(trim(canonical_name), '\\s+', ' ', 'g'))
          HAVING COUNT(*) > 1
        )
        SELECT normalized_name, project_count, projects
        FROM grouped
        ORDER BY project_count DESC, normalized_name
        LIMIT 100
        """
    )
    duplicate_rows = await duplicates_cursor.fetchall()

    candidate_cursor = await request.app.state.db.execute(
        """
        SELECT
          state::text AS state,
          COUNT(*)::int AS count,
          COUNT(*) FILTER (WHERE score >= 0.85)::int AS high_confidence_count
        FROM entity_match_candidate
        GROUP BY state
        ORDER BY state
        """
    )
    candidate_rows = await candidate_cursor.fetchall()

    unresolved_cursor = await request.app.state.db.execute(
        """
        SELECT
          emc.id,
          emc.score,
          emc.proposed_relationship::text AS proposed_relationship,
          left_project.id AS left_id,
          left_project.canonical_name AS left_name,
          right_project.id AS right_id,
          right_project.canonical_name AS right_name,
          emc.signals
        FROM entity_match_candidate emc
        JOIN project left_project ON left_project.id = emc.left_project_id
        JOIN project right_project ON right_project.id = emc.right_project_id
        WHERE emc.state = 'candidate'
          AND emc.score >= 0.85
        ORDER BY emc.score DESC, emc.created_at
        LIMIT 100
        """
    )
    unresolved_rows = await unresolved_cursor.fetchall()

    conflicts_cursor = await request.app.state.db.execute(
        """
        WITH latest_per_source AS (
          SELECT DISTINCT ON (a.project_id, a.field, a.source_id)
            a.project_id,
            a.field,
            a.source_id,
            a.value::text AS value_text,
            a.observed_at
          FROM assertion a
          WHERE a.field IN (
            'address', 'residential_units', 'site_acres', 'planned_completion',
            'official_status_text', 'permit_number', 'planning_case'
          )
            AND a.observed_at >= now() - interval '365 days'
          ORDER BY a.project_id, a.field, a.source_id, a.observed_at DESC
        ), conflicting AS (
          SELECT
            project_id,
            field,
            COUNT(DISTINCT value_text)::int AS distinct_values,
            jsonb_agg(DISTINCT value_text) AS values
          FROM latest_per_source
          GROUP BY project_id, field
          HAVING COUNT(DISTINCT value_text) > 1
        )
        SELECT
          conflicting.project_id,
          p.canonical_name AS project_name,
          conflicting.field,
          conflicting.distinct_values,
          conflicting.values
        FROM conflicting
        JOIN project p ON p.id = conflicting.project_id
        ORDER BY conflicting.distinct_values DESC, p.canonical_name, conflicting.field
        LIMIT 100
        """
    )
    conflict_rows = await conflicts_cursor.fetchall()

    sample_cursor = await request.app.state.db.execute(
        """
        SELECT
          p.id,
          p.canonical_name,
          p.project_type,
          p.last_activity_at,
          p.primary_geometry IS NOT NULL AS mapped,
          COUNT(DISTINCT psr.source_record_id)::int AS source_record_count,
          COALESCE(
            (SELECT jsonb_object_agg(dimension, value)
             FROM project_status_dimension psd
             WHERE psd.project_id = p.id),
            '{}'::jsonb
          ) AS statuses
        FROM project p
        LEFT JOIN project_source_record psr ON psr.project_id = p.id
        GROUP BY p.id
        ORDER BY md5(p.id::text || current_date::text)
        LIMIT 20
        """
    )
    sample_rows = await sample_cursor.fetchall()

    candidates = {
        str(row["state"]): {
            "count": int(row["count"] or 0),
            "high_confidence_count": int(row["high_confidence_count"] or 0),
        }
        for row in candidate_rows
    }

    return {
        "duplicate_name_groups": [
            {
                "normalized_name": row["normalized_name"],
                "project_count": int(row["project_count"]),
                "projects": row["projects"] or [],
            }
            for row in duplicate_rows
        ],
        "match_candidates": candidates,
        "high_confidence_unresolved_candidates": [
            {
                "id": str(row["id"]),
                "score": float(row["score"]),
                "proposed_relationship": row["proposed_relationship"],
                "left": {"id": str(row["left_id"]), "name": row["left_name"]},
                "right": {"id": str(row["right_id"]), "name": row["right_name"]},
                "signals": row["signals"] or {},
            }
            for row in unresolved_rows
        ],
        "conflicting_current_assertions": [
            {
                "project_id": str(row["project_id"]),
                "project_name": row["project_name"],
                "field": row["field"],
                "distinct_values": int(row["distinct_values"]),
                "values": row["values"] or [],
            }
            for row in conflict_rows
        ],
        "manual_qa_sample": [
            {
                "id": str(row["id"]),
                "name": row["canonical_name"],
                "project_type": row["project_type"],
                "last_activity_at": row["last_activity_at"].isoformat() if row["last_activity_at"] else None,
                "mapped": bool(row["mapped"]),
                "source_record_count": int(row["source_record_count"] or 0),
                "statuses": row["statuses"] or {},
            }
            for row in sample_rows
        ],
        "metadata": {
            "duplicate_name_group_count": len(duplicate_rows),
            "high_confidence_unresolved_count": len(unresolved_rows),
            "conflicting_assertion_count": len(conflict_rows),
            "manual_sample_count": len(sample_rows),
            "note": (
                "Audit only. Duplicate names and conflicting source assertions require evidence review; "
                "they are never automatic merge instructions."
            ),
        },
    }
