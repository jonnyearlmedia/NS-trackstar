from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request

from ns_trackstar_api.source_policy import source_freshness_policy

router = APIRouter()


def _latest_outcome(success: bool | None, records_changed: int | None) -> str | None:
    if success is None:
        return None
    if not success:
        return "failed"
    return "changed" if int(records_changed or 0) > 0 else "checked_no_change"


def _stability_state(attempts: int, successful_runs: int) -> tuple[str, float | None]:
    if attempts <= 0:
        return "insufficient_history", None
    success_rate = successful_runs / attempts
    if attempts < 3:
        return "insufficient_history", success_rate
    if success_rate >= 0.9:
        return "stable", success_rate
    if success_rate >= 0.75:
        return "watch", success_rate
    return "unstable", success_rate


def _missed_expected_check(
    *,
    last_attempt_at: datetime | None,
    poll_interval_minutes: int,
    now: datetime,
) -> tuple[bool, datetime | None, int | None]:
    if last_attempt_at is None:
        return True, None, None
    if last_attempt_at.tzinfo is None:
        last_attempt_at = last_attempt_at.replace(tzinfo=UTC)
    grace_minutes = max(15, round(poll_interval_minutes * 0.25))
    expected_by = last_attempt_at + timedelta(minutes=poll_interval_minutes + grace_minutes)
    overdue_minutes = max(0, int((now - expected_by).total_seconds() // 60))
    return now > expected_by, expected_by, overdue_minutes


def _policy_state(source_key: str, poll_interval_minutes: int) -> dict:
    policy = source_freshness_policy(source_key)
    if policy is None:
        return {
            "freshness_class": "unclassified",
            "meaningful_change_window": None,
            "recommended_min_minutes": None,
            "recommended_max_minutes": None,
            "cadence_policy_state": "unclassified",
            "rationale": None,
        }
    if poll_interval_minutes < policy.recommended_min_minutes:
        policy_state = "faster_than_needed"
    elif poll_interval_minutes > policy.recommended_max_minutes:
        policy_state = "slower_than_recommended"
    else:
        policy_state = "within_policy"
    return {
        "freshness_class": policy.freshness_class,
        "meaningful_change_window": policy.meaningful_change_window,
        "recommended_min_minutes": policy.recommended_min_minutes,
        "recommended_max_minutes": policy.recommended_max_minutes,
        "cadence_policy_state": policy_state,
        "rationale": policy.rationale,
    }


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
          COALESCE(stats.attempts, 0)::int AS attempts,
          COALESCE(stats.successful_runs, 0)::int AS successful_runs,
          COALESCE(stats.runs_with_changes, 0)::int AS runs_with_changes,
          COALESCE(stats.records_changed, 0)::int AS records_changed,
          stats.avg_response_latency_ms,
          latest.success AS latest_success,
          latest.records_returned AS latest_records_returned,
          latest.records_changed AS latest_records_changed,
          latest.started_at AS latest_started_at,
          latest.finished_at AS latest_finished_at,
          latest.error_type AS latest_error_type,
          latest.error_message AS latest_error_message
        FROM source s
        LEFT JOIN source_health sh ON sh.source_id = s.id
        LEFT JOIN LATERAL (
          SELECT
            COUNT(*)::int AS attempts,
            COUNT(*) FILTER (WHERE success IS TRUE)::int AS successful_runs,
            COUNT(*) FILTER (
              WHERE success IS TRUE AND records_changed > 0
            )::int AS runs_with_changes,
            COALESCE(SUM(records_changed) FILTER (WHERE success IS TRUE), 0)::int AS records_changed,
            ROUND(AVG(response_latency_ms) FILTER (WHERE success IS TRUE))::int
              AS avg_response_latency_ms
          FROM source_run
          WHERE source_id = s.id
            AND started_at >= now() - (%(days)s * interval '1 day')
        ) stats ON true
        LEFT JOIN LATERAL (
          SELECT
            success,
            records_returned,
            records_changed,
            started_at,
            finished_at,
            error_type,
            error_message
          FROM source_run
          WHERE source_id = s.id
          ORDER BY started_at DESC
          LIMIT 1
        ) latest ON true
        ORDER BY s.poll_interval_minutes, s.source_key
        """,
        {"days": days},
    )
    rows = await cursor.fetchall()

    now = datetime.now(UTC)
    items = []
    for row in rows:
        attempts = int(row["attempts"] or 0)
        successful_runs = int(row["successful_runs"] or 0)
        runs_with_changes = int(row["runs_with_changes"] or 0)
        change_run_rate = runs_with_changes / successful_runs if successful_runs else None
        stability_state, success_rate = _stability_state(attempts, successful_runs)
        poll_interval_minutes = int(row["poll_interval_minutes"])
        missed_check, expected_by, overdue_minutes = _missed_expected_check(
            last_attempt_at=row["last_attempt_at"],
            poll_interval_minutes=poll_interval_minutes,
            now=now,
        )
        policy = _policy_state(str(row["source_key"]), poll_interval_minutes)
        items.append(
            {
                "source_key": row["source_key"],
                "name": row["name"],
                "source_family": row["source_family"],
                "jurisdiction": row["jurisdiction"],
                "authority_class": row["authority_class"],
                "collector_type": row["collector_type"],
                "poll_interval_minutes": poll_interval_minutes,
                **policy,
                "enabled": bool(row["enabled"]),
                "health_state": row["health_state"],
                "stability_state": stability_state,
                "success_rate": round(success_rate, 4) if success_rate is not None else None,
                "last_attempt_at": row["last_attempt_at"].isoformat() if row["last_attempt_at"] else None,
                "last_success_at": row["last_success_at"].isoformat() if row["last_success_at"] else None,
                "last_content_change_at": (
                    row["last_content_change_at"].isoformat()
                    if row["last_content_change_at"]
                    else None
                ),
                "expected_next_check_by": expected_by.isoformat() if expected_by else None,
                "missed_expected_check": missed_check,
                "overdue_minutes": overdue_minutes,
                "consecutive_failures": int(row["consecutive_failures"] or 0),
                "attempts": attempts,
                "successful_runs": successful_runs,
                "runs_with_changes": runs_with_changes,
                "records_changed": int(row["records_changed"] or 0),
                "change_run_rate": round(change_run_rate, 4) if change_run_rate is not None else None,
                "avg_response_latency_ms": (
                    int(row["avg_response_latency_ms"])
                    if row["avg_response_latency_ms"] is not None
                    else None
                ),
                "latest_run": {
                    "outcome": _latest_outcome(
                        row["latest_success"],
                        row["latest_records_changed"],
                    ),
                    "success": row["latest_success"],
                    "records_returned": int(row["latest_records_returned"] or 0),
                    "records_changed": int(row["latest_records_changed"] or 0),
                    "started_at": (
                        row["latest_started_at"].isoformat() if row["latest_started_at"] else None
                    ),
                    "finished_at": (
                        row["latest_finished_at"].isoformat() if row["latest_finished_at"] else None
                    ),
                    "error_type": row["latest_error_type"],
                    "error_message": row["latest_error_message"],
                },
            }
        )

    return {
        "items": items,
        "metadata": {
            "window_days": days,
            "source_count": len(items),
            "checked_at": now.isoformat(),
            "missed_expected_checks": sum(1 for item in items if item["missed_expected_check"]),
            "unstable_sources": sum(1 for item in items if item["stability_state"] == "unstable"),
            "watch_sources": sum(1 for item in items if item["stability_state"] == "watch"),
            "unclassified_sources": sum(
                1 for item in items if item["cadence_policy_state"] == "unclassified"
            ),
            "slower_than_recommended": sum(
                1 for item in items if item["cadence_policy_state"] == "slower_than_recommended"
            ),
            "faster_than_needed": sum(
                1 for item in items if item["cadence_policy_state"] == "faster_than_needed"
            ),
            "note": (
                "Cadence policy describes how quickly the underlying source can meaningfully "
                "change. Actual polling still requires source-specific health and cost review."
            ),
        },
    }
