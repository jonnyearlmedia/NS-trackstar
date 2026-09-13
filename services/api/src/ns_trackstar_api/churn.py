from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/admin/sources/{source_key}/churn-fields")
async def source_churn_fields(request: Request, source_key: str) -> dict:
    """Show which normalized fields changed during the latest successful source run.

    This is an internal QA endpoint for diagnosing noisy collectors. It compares each
    snapshot written during the latest successful run with that record's immediately
    previous snapshot and counts top-level normalized fields that differ.
    """

    source_cursor = await request.app.state.db.execute(
        "SELECT id, name FROM source WHERE source_key = %s",
        (source_key,),
    )
    source = await source_cursor.fetchone()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    run_cursor = await request.app.state.db.execute(
        """
        SELECT id, started_at, finished_at, records_returned, records_changed
        FROM source_run
        WHERE source_id = %s AND success IS TRUE
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (source["id"],),
    )
    run = await run_cursor.fetchone()
    if run is None:
        return {
            "source_key": source_key,
            "source_name": source["name"],
            "latest_run": None,
            "changed_snapshot_count": 0,
            "field_changes": [],
            "samples": [],
        }

    cursor = await request.app.state.db.execute(
        """
        WITH current_snapshots AS (
          SELECT
            ss.id,
            ss.source_record_id,
            ss.observed_at,
            ss.normalized_payload,
            sr.external_id
          FROM source_snapshot ss
          JOIN source_record sr ON sr.id = ss.source_record_id
          WHERE sr.source_id = %(source_id)s
            AND ss.observed_at >= %(started_at)s
            AND ss.observed_at <= COALESCE(%(finished_at)s, now()) + interval '1 minute'
        ),
        paired AS (
          SELECT
            current.id,
            current.source_record_id,
            current.external_id,
            current.observed_at,
            current.normalized_payload AS current_payload,
            previous.normalized_payload AS previous_payload
          FROM current_snapshots current
          LEFT JOIN LATERAL (
            SELECT prior.normalized_payload
            FROM source_snapshot prior
            WHERE prior.source_record_id = current.source_record_id
              AND prior.observed_at < current.observed_at
            ORDER BY prior.observed_at DESC
            LIMIT 1
          ) previous ON true
        ),
        field_diffs AS (
          SELECT
            paired.external_id,
            paired.observed_at,
            key,
            paired.previous_payload -> key AS previous_value,
            paired.current_payload -> key AS current_value
          FROM paired
          CROSS JOIN LATERAL jsonb_object_keys(
            COALESCE(paired.previous_payload, '{}'::jsonb)
            || COALESCE(paired.current_payload, '{}'::jsonb)
          ) key
          WHERE paired.previous_payload IS NOT NULL
            AND paired.previous_payload -> key IS DISTINCT FROM paired.current_payload -> key
        )
        SELECT
          key,
          COUNT(*)::int AS changed_records,
          MIN(external_id) AS example_external_id,
          jsonb_agg(
            jsonb_build_object(
              'external_id', external_id,
              'observed_at', observed_at,
              'previous', previous_value,
              'current', current_value
            )
            ORDER BY observed_at DESC
          ) FILTER (WHERE external_id IS NOT NULL) AS examples
        FROM field_diffs
        GROUP BY key
        ORDER BY changed_records DESC, key
        """,
        {
            "source_id": source["id"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
        },
    )
    rows = await cursor.fetchall()

    count_cursor = await request.app.state.db.execute(
        """
        SELECT COUNT(*)::int AS count
        FROM source_snapshot ss
        JOIN source_record sr ON sr.id = ss.source_record_id
        WHERE sr.source_id = %s
          AND ss.observed_at >= %s
          AND ss.observed_at <= COALESCE(%s, now()) + interval '1 minute'
        """,
        (source["id"], run["started_at"], run["finished_at"]),
    )
    changed_count_row = await count_cursor.fetchone()

    return {
        "source_key": source_key,
        "source_name": source["name"],
        "latest_run": {
            "id": str(run["id"]),
            "started_at": run["started_at"].isoformat(),
            "finished_at": run["finished_at"].isoformat() if run["finished_at"] else None,
            "records_returned": int(run["records_returned"] or 0),
            "records_changed": int(run["records_changed"] or 0),
        },
        "changed_snapshot_count": int(changed_count_row["count"] or 0),
        "field_changes": [
            {
                "field": row["key"],
                "changed_records": int(row["changed_records"]),
                "example_external_id": row["example_external_id"],
            }
            for row in rows
        ],
        "samples": [
            {
                "field": row["key"],
                "examples": (row["examples"] or [])[:3],
            }
            for row in rows[:8]
        ],
        "metadata": {
            "note": (
                "Internal collector QA. A field that changes on many records every run may be "
                "request-volatile and should not drive public change detection."
            )
        },
    }
