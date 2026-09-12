from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

router = APIRouter()


@router.get("/admin/sources/cadence")
async def source_cadence_audit(
    request: Request,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> dict:
    """Describe real source polling behavior without auto-tuning it.

    The audit deliberately separates configured cadence from observed usefulness. A
    source that is healthy but almost never changes should not automatically be polled
    faster; a source that changes frequently can be reviewed for a tighter interval.
    """

    cursor = await request.app.state.db.execute(
        """
        SELECT
          s.source_key,
          s.name,
          s.source_family,
          s.jurisdiction,
          s.authority_class,
          s.collector_type,
          s.poll_interval_minutes,
          s.enabled,
          sh.health_state,
          sh.last_attempt_at,
          sh.last_success_at,
          sh.last_content_change_at,
          sh.consecutive_failures,
          COUNT(sr.id) FILTER (
            WHERE sr.started_at >= now() - (%(days)s * interval '1 day')
          )::int AS attempts,
          COUNT(sr.id) FILTER (
            WHERE sr.started_at >= now() - (%(days)s * interval '1 day')
              AND sr.success IS TRUE
          )::int AS successful_runs,
          COUNT(sr.id) FILTER (
            WHERE sr.started_at >= now() - (%(days)s * interval '1 day')
              AND sr.success IS TRUE
              AND sr.records_changed > 0
          )::int AS runs_with_changes,
          COALESCE(SUM(sr.records_changed) FILTER (
            WHERE sr.started_at >= now() - (%(days)s * interval '1 day')
              AND sr.success IS TRUE
          ), 0)::int AS records_changed,
          ROUND(AVG(sr.response_latency_ms) FILTER (
            WHERE sr.started_at >= now() - (%(days)s * interval '1 day')
              AND sr.success IS TRUE
          ))::int AS avg_response_latency_ms
        FROM source s
        LEFT JOIN source_health sh ON sh.source_id = s.id
        LEFT JOIN source_run sr ON sr.source_id = s.id
        GROUP BY
          s.id,
          sh.health_state,
          sh.last_attempt_at,
          sh.last_success_at,
          sh.last_content_change_at,
          sh.consecutive_failures
        ORDER BY s.poll_interval_minutes, s.source_key
        """,
        {"days": days},
    )
    rows = await cursor.fetchall()

    items = []
    for row in rows:
        successful_runs = int(row["successful_runs"] or 0)
        runs_with_changes = int(row["runs_with_changes"] or 0)
        change_run_rate = runs_with_changes / successful_runs if successful_runs else None
        items.append(
            {
                "source_key": row["source_key"],
                "name": row["name"],
                "source_family": row["source_family"],
                "jurisdiction": row["jurisdiction"],
                "authority_class": row["authority_class"],
                "collector_type": row["collector_type"],
                "poll_interval_minutes": int(row["poll_interval_minutes"]),
                "enabled": bool(row["enabled"]),
                "health_state": row["health_state"],
                "last_attempt_at": row["last_attempt_at"].isoformat() if row["last_attempt_at"] else None,
                "last_success_at": row["last_success_at"].isoformat() if row["last_success_at"] else None,
                "last_content_change_at": (
                    row["last_content_change_at"].isoformat()
                    if row["last_content_change_at"]
                    else None
                ),
                "consecutive_failures": int(row["consecutive_failures"] or 0),
                "attempts": int(row["attempts"] or 0),
                "successful_runs": successful_runs,
                "runs_with_changes": runs_with_changes,
                "records_changed": int(row["records_changed"] or 0),
                "change_run_rate": round(change_run_rate, 4) if change_run_rate is not None else None,
                "avg_response_latency_ms": (
                    int(row["avg_response_latency_ms"])
                    if row["avg_response_latency_ms"] is not None
                    else None
                ),
            }
        )

    return {
        "items": items,
        "metadata": {
            "window_days": days,
            "source_count": len(items),
            "note": (
                "Descriptive audit only. Polling changes require source-by-source review of "
                "change frequency, source cost/restrictions, and public freshness value."
            ),
        },
    }
