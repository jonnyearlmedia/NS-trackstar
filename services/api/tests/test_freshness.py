from datetime import UTC, datetime, timedelta

from ns_trackstar_api.freshness import freshness_state, stale_after_minutes


def test_stale_threshold_uses_each_sources_own_poll_interval() -> None:
    assert stale_after_minutes(5) == 30
    assert stale_after_minutes(60) == 120
    assert stale_after_minutes(240) == 480


def test_recent_success_is_current() -> None:
    now = datetime(2026, 9, 12, 22, 0, tzinfo=UTC)
    state, age = freshness_state(
        last_success_at=now - timedelta(minutes=45),
        poll_interval_minutes=60,
        now=now,
    )
    assert state == "current"
    assert age == 45


def test_old_success_is_stale() -> None:
    now = datetime(2026, 9, 12, 22, 0, tzinfo=UTC)
    state, age = freshness_state(
        last_success_at=now - timedelta(minutes=121),
        poll_interval_minutes=60,
        now=now,
    )
    assert state == "stale"
    assert age == 121


def test_missing_success_is_unknown() -> None:
    state, age = freshness_state(
        last_success_at=None,
        poll_interval_minutes=60,
        now=datetime(2026, 9, 12, 22, 0, tzinfo=UTC),
    )
    assert state == "unknown"
    assert age is None
