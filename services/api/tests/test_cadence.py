from datetime import UTC, datetime, timedelta

from ns_trackstar_api.cadence import _latest_outcome, _missed_expected_check, _stability_state


def test_latest_outcome_distinguishes_no_change_from_failure() -> None:
    assert _latest_outcome(True, 3) == "changed"
    assert _latest_outcome(True, 0) == "checked_no_change"
    assert _latest_outcome(False, 0) == "failed"
    assert _latest_outcome(None, None) is None


def test_stability_state_requires_enough_history() -> None:
    assert _stability_state(0, 0) == ("insufficient_history", None)
    assert _stability_state(2, 2) == ("insufficient_history", 1.0)


def test_stability_state_surfaces_repeated_failures() -> None:
    assert _stability_state(10, 10) == ("stable", 1.0)
    assert _stability_state(10, 8) == ("watch", 0.8)
    assert _stability_state(10, 5) == ("unstable", 0.5)


def test_missed_check_uses_interval_plus_scheduler_grace() -> None:
    now = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)
    missed, expected_by, overdue = _missed_expected_check(
        last_attempt_at=now - timedelta(minutes=80),
        poll_interval_minutes=60,
        now=now,
    )
    assert missed is True
    assert expected_by == now - timedelta(minutes=5)
    assert overdue == 5


def test_recent_source_is_not_marked_missed() -> None:
    now = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)
    missed, expected_by, overdue = _missed_expected_check(
        last_attempt_at=now - timedelta(minutes=65),
        poll_interval_minutes=60,
        now=now,
    )
    assert missed is False
    assert expected_by == now + timedelta(minutes=10)
    assert overdue == 0


def test_never_attempted_source_is_marked_missed() -> None:
    missed, expected_by, overdue = _missed_expected_check(
        last_attempt_at=None,
        poll_interval_minutes=240,
        now=datetime(2026, 9, 12, 20, 0, tzinfo=UTC),
    )
    assert missed is True
    assert expected_by is None
    assert overdue is None
