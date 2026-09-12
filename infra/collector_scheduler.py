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
from pathlib import Path


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

    # Running each source on startup makes a fresh deployment useful without
    # waiting up to 24 hours. Subsequent runs honor per-source poll_minutes.
    next_run = {source.key: 0.0 for source in sources}
    tick_seconds = max(5, int(os.environ.get("SCHEDULER_TICK_SECONDS", "60")))

    while not stopping:
        now = time.monotonic()
        for source in sources:
            if stopping:
                break
            if now < next_run[source.key]:
                continue
            collect(source, dry_run=args.dry_run)
            next_run[source.key] = time.monotonic() + source.poll_seconds

        if args.once:
            return 0
        time.sleep(tick_seconds)

    return 0


if __name__ == "__main__":
    sys.exit(main())
