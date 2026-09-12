"""Low-concurrency scheduler for production source configurations.

Every source is collected sequentially and on its own configured poll interval.
A failed source is logged and isolated; it does not prevent later sources from
running or stop the scheduler. Collector run/source-health persistence remains
owned by ``ns-trackstar-ingest``.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg


@dataclass(frozen=True)
class ScheduledSource:
    path: Path
    key: str
    poll_seconds: int


def load_sources(config_dir: Path) -> list[ScheduledSource]:
    sources: list[ScheduledSource] = []
    for path in sorted(config_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        poll_minutes = int(data["poll_minutes"])
        if poll_minutes <= 0:
            raise ValueError(f"{path}: poll_minutes must be positive")
        sources.append(
            ScheduledSource(
                path=path,
                key=str(data["key"]),
                poll_seconds=poll_minutes * 60,
            )
        )
    if not sources:
        raise RuntimeError(f"No source configurations found in {config_dir}")
    return sources


def collect(source: ScheduledSource, *, dry_run: bool) -> int:
    command = ["ns-trackstar-ingest", "collect", str(source.path)]
    if not dry_run:
        command.append("--write")
    print(
        json.dumps({"event": "collector_start", "source": source.key, "command": command}),
        flush=True,
    )
    completed = subprocess.run(command, check=False)
    print(
        json.dumps(
            {
                "event": "collector_finish",
                "source": source.key,
                "exit_code": completed.returncode,
            }
        ),
        flush=True,
    )
    return completed.returncode


def persisted_last_attempts(database_url: str | None) -> dict[str, datetime]:
    """Read durable healthy-source progress so a restart is not a full re-crawl.

    Broken and schema-changed sources are intentionally omitted so a deployment that
    contains a collector/config fix retries them immediately. Blocked sources retain
    their normal cadence to avoid hammering an upstream anti-bot boundary.
    """
    if not database_url:
        return {}
    try:
        with psycopg.connect(database_url) as conn:
            rows = conn.execute(
                """
                SELECT s.source_key, sh.last_attempt_at
                FROM source s
                JOIN source_health sh ON sh.source_id = s.id
                WHERE sh.last_attempt_at IS NOT NULL
                  AND sh.health_state IN ('healthy', 'delayed', 'blocked')
                """
            ).fetchall()
    except psycopg.Error as exc:
        print(
            json.dumps(
                {
                    "event": "scheduler_state_unavailable",
                    "reason": str(exc),
                    "fallback": "run_sources_now",
                }
            ),
            flush=True,
        )
        return {}
    return {str(source_key): attempted_at for source_key, attempted_at in rows}


def persisted_failure_state(
    database_url: str | None,
    *,
    source_key: str,
) -> tuple[str | None, int]:
    """Read the collector-owned health state after a failed subprocess.

    Retry decisions fail closed: if health cannot be read, the scheduler uses the
    source's normal poll interval rather than guessing that an upstream is safe to retry.
    """
    if not database_url:
        return None, 0
    try:
        with psycopg.connect(database_url) as conn:
            row = conn.execute(
                """
                SELECT sh.health_state::text, sh.consecutive_failures
                FROM source s
                LEFT JOIN source_health sh ON sh.source_id = s.id
                WHERE s.source_key = %s
                """,
                (source_key,),
            ).fetchone()
    except psycopg.Error as exc:
        print(
            json.dumps(
                {
                    "event": "scheduler_failure_state_unavailable",
                    "source": source_key,
                    "reason": str(exc),
                    "fallback": "normal_poll_interval",
                }
            ),
            flush=True,
        )
        return None, 0
    if row is None:
        return None, 0
    return (str(row[0]) if row[0] is not None else None, int(row[1] or 0))


def retry_delay_seconds(
    source: ScheduledSource,
    *,
    health_state: str | None,
    consecutive_failures: int,
) -> int:
    """Return a conservative retry delay for a persisted collector failure.

    Only transient-looking broken/degraded states get a shortened retry. Blocked,
    schema-changed, unknown and other states keep the normal configured cadence so the
    scheduler never turns access restrictions or schema drift into a retry storm.
    """
    if health_state not in {"broken", "degraded"}:
        return source.poll_seconds

    base_retry = min(
        source.poll_seconds,
        max(300, min(900, source.poll_seconds // 4)),
    )
    exponent = max(0, min(consecutive_failures - 1, 4))
    return min(source.poll_seconds, base_retry * (2**exponent))


def seconds_until_due(
    source: ScheduledSource,
    *,
    last_attempt: datetime | None,
    now: datetime,
) -> float:
    if last_attempt is None:
        return 0.0
    if last_attempt.tzinfo is None:
        last_attempt = last_attempt.replace(tzinfo=UTC)
    elapsed = max(0.0, (now.astimezone(UTC) - last_attempt.astimezone(UTC)).total_seconds())
    return max(0.0, source.poll_seconds - elapsed)


def initial_schedule(
    sources: list[ScheduledSource],
    *,
    database_url: str | None,
    force_now: bool,
) -> dict[str, float]:
    """Translate persisted wall-clock attempts into monotonic next-run deadlines."""
    if force_now:
        return {source.key: 0.0 for source in sources}

    last_attempts = persisted_last_attempts(database_url)
    wall_now = datetime.now(UTC)
    monotonic_now = time.monotonic()
    schedule: dict[str, float] = {}

    for source in sources:
        last_attempt = last_attempts.get(source.key)
        remaining = seconds_until_due(source, last_attempt=last_attempt, now=wall_now)
        schedule[source.key] = 0.0 if last_attempt is None else monotonic_now + remaining
        if last_attempt is not None and remaining > 0:
            print(
                json.dumps(
                    {
                        "event": "collector_deferred_after_restart",
                        "source": source.key,
                        "seconds_until_due": int(remaining),
                        "last_attempt_at": last_attempt.isoformat(),
                    }
                ),
                flush=True,
            )
    return schedule


def main() -> int:
    parser = argparse.ArgumentParser(prog="ns-trackstar-collector-scheduler")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(os.environ.get("COLLECTOR_CONFIG_DIR", "/app/config/sources")),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sources = load_sources(args.config_dir)
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    database_url = os.environ.get("DATABASE_URL")

    # Persisted source_health makes deployment restarts cheap: successful/recent
    # sources keep the remaining portion of their configured interval, while a
    # previously failed source is retried immediately after a deploy that may fix it.
    # Brand-new sources also run immediately. ``--once`` deliberately forces all
    # configs for operator smoke testing.
    next_run = initial_schedule(
        sources,
        database_url=database_url,
        force_now=args.once or args.dry_run,
    )
    tick_seconds = max(5, int(os.environ.get("SCHEDULER_TICK_SECONDS", "60")))

    while not stopping:
        now = time.monotonic()
        for source in sources:
            if stopping:
                break
            if now < next_run[source.key]:
                continue

            exit_code = collect(source, dry_run=args.dry_run)
            delay = source.poll_seconds
            if exit_code != 0 and not args.dry_run:
                health_state, consecutive_failures = persisted_failure_state(
                    database_url,
                    source_key=source.key,
                )
                delay = retry_delay_seconds(
                    source,
                    health_state=health_state,
                    consecutive_failures=consecutive_failures,
                )
                print(
                    json.dumps(
                        {
                            "event": "collector_retry_scheduled",
                            "source": source.key,
                            "health_state": health_state,
                            "consecutive_failures": consecutive_failures,
                            "retry_in_seconds": delay,
                            "normal_poll_seconds": source.poll_seconds,
                        }
                    ),
                    flush=True,
                )
            next_run[source.key] = time.monotonic() + delay

        if args.once:
            return 0
        time.sleep(tick_seconds)

    return 0


if __name__ == "__main__":
    sys.exit(main())
