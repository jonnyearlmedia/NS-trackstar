from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from infra.collector_scheduler import ScheduledSource, seconds_until_due


def test_scheduler_preserves_remaining_poll_interval_after_restart() -> None:
    source = ScheduledSource(Path("source.json"), "test.source", 3600)
    now = datetime(2026, 9, 12, 7, 0, tzinfo=UTC)
    last_attempt = now - timedelta(minutes=10)

    assert seconds_until_due(source, last_attempt=last_attempt, now=now) == pytest.approx(3000)


def test_scheduler_runs_brand_new_or_overdue_source_immediately() -> None:
    source = ScheduledSource(Path("source.json"), "test.source", 3600)
    now = datetime(2026, 9, 12, 7, 0, tzinfo=UTC)

    assert seconds_until_due(source, last_attempt=None, now=now) == 0
    assert seconds_until_due(
        source,
        last_attempt=now - timedelta(hours=2),
        now=now,
    ) == 0
