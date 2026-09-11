from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ns_trackstar.models import SourceHealthState


@dataclass(frozen=True, slots=True)
class RunSignal:
    success: bool
    parse_ok: bool
    canary_ok: bool
    consecutive_failures: int
    last_success_at: datetime | None
    expected_poll_minutes: int
    blocked: bool = False
    schema_changed: bool = False


def classify_health(signal: RunSignal, *, now: datetime | None = None) -> SourceHealthState:
    """Convert collector telemetry into an operational health state.

    A zero-record run is not considered healthy unless request, parse, and canary all succeed.
    """
    now = now or datetime.now(timezone.utc)

    if signal.blocked:
        return SourceHealthState.BLOCKED
    if signal.schema_changed:
        return SourceHealthState.SCHEMA_CHANGED
    if not signal.success or signal.consecutive_failures >= 3:
        return SourceHealthState.BROKEN
    if not signal.parse_ok or not signal.canary_ok:
        return SourceHealthState.DEGRADED
    if signal.last_success_at is None:
        return SourceHealthState.DELAYED

    max_age = timedelta(minutes=max(signal.expected_poll_minutes * 2, 15))
    if now - signal.last_success_at > max_age:
        return SourceHealthState.DELAYED

    return SourceHealthState.HEALTHY
