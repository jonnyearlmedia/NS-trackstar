from datetime import UTC, datetime, timedelta

from ns_trackstar_api.freshness import aggregate_freshness, freshness_state, stale_after_minutes
from ns_trackstar_api.public_changes import SUPPRESSED_PUBLIC_SOURCE_KEYS


def test_noisy_civicclerk_source_is_suppressed_from_public_updates() -> None:
    assert "vallejo.civicclerk" in SUPPRESSED_PUBLIC_SOURCE_KEYS


def test_source_specific_stale_threshold_tracks_each_poll_interval() -> None:
    assert stale_after_minutes(60) == 120
    assert stale_after_minutes(240) == 480
    assert stale_after_minutes(1440) == 2880


def test_freshness_is_conservative_when_any_project_source_is_stale_or_unknown() -> None:
    assert aggregate_freshness(["current", "current"]) == "current"
    assert aggregate_freshness(["current", "unknown"]) == "unknown"
    assert aggregate_freshness(["current", "stale"]) == "stale"


def test_last_success_age_drives_public_stale_state() -> None:
    now = datetime(2026, 9, 13, 7, 0, tzinfo=UTC)
    state, age = freshness_state(
        last_success_at=now - timedelta(minutes=121),
        poll_interval_minutes=60,
        now=now,
    )
    assert state == "stale"
    assert age == 121
