from datetime import UTC, datetime

from ns_trackstar.health import RunSignal, classify_health
from ns_trackstar.models import SourceHealthState


def test_failed_request_is_broken() -> None:
    signal = RunSignal(
        success=False,
        parse_ok=False,
        canary_ok=False,
        consecutive_failures=1,
        last_success_at=None,
        expected_poll_minutes=240,
    )
    assert classify_health(signal) == SourceHealthState.BROKEN


def test_schema_change_is_not_reported_as_no_new_records() -> None:
    now = datetime.now(UTC)
    signal = RunSignal(
        success=True,
        parse_ok=False,
        canary_ok=False,
        consecutive_failures=0,
        last_success_at=now,
        expected_poll_minutes=240,
        schema_changed=True,
    )
    assert classify_health(signal, now=now) == SourceHealthState.SCHEMA_CHANGED


def test_clean_run_is_healthy() -> None:
    now = datetime.now(UTC)
    signal = RunSignal(
        success=True,
        parse_ok=True,
        canary_ok=True,
        consecutive_failures=0,
        last_success_at=now,
        expected_poll_minutes=240,
    )
    assert classify_health(signal, now=now) == SourceHealthState.HEALTHY
