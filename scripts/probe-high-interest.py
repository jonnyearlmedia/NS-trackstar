#!/usr/bin/env python3
"""Re-measure the high-interest portfolio against a running Trackstar API.

The portfolio file records what was true when it was written. This re-measures it,
so the claim in the file can be checked rather than trusted, and so a project that
quietly stops being findable is noticed by us rather than by a resident.

    ./scripts/probe-high-interest.py [--api https://host] [--write]

--write updates the tiers in fixtures/high-interest/portfolio.json.
Without it, nothing is modified and the diff is printed.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

import httpx

PORTFOLIO = pathlib.Path(__file__).resolve().parent.parent / (
    "fixtures/high-interest/portfolio.json"
)
DEFAULT_API = "https://15-204-82-184.sslip.io"


def _words(value: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9 ]", " ", value.lower()).split())


def _best_match(query: str, hits: list[dict]) -> dict | None:
    """The closest hit, or nothing. Deliberately strict.

    A loose match here would let the gate go green on a different project with a
    similar name, which is worse than going red: it would report coverage we do not
    have for the exact projects this file exists to protect.
    """
    wanted = _words(query)
    best = None
    for hit in hits:
        overlap = len(wanted & _words(hit.get("name") or "")) / max(1, len(wanted))
        if overlap >= 0.6 and (best is None or overlap > best["_overlap"]):
            best = dict(hit, _overlap=round(overlap, 2))
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    document = json.loads(PORTFOLIO.read_text())
    changes: list[str] = []
    counts: dict[str, int] = {}

    with httpx.Client(timeout=30) as client:
        for project in document["projects"]:
            query = project["queries"][0]
            try:
                response = client.get(
                    f"{args.api.rstrip('/')}/search/projects",
                    params={"q": query, "limit": 8},
                )
                hits = response.json() if response.status_code == 200 else []
            except httpx.HTTPError as exc:
                print(f"! {query}: {type(exc).__name__}", file=sys.stderr)
                hits = []

            match = _best_match(query, hits)
            if match is None:
                tier = "watchlist"
            elif match.get("geometry") is not None:
                tier = "guaranteed"
            else:
                tier = "found_unmapped"

            if tier != project["tier"]:
                changes.append(f"{project['label']}: {project['tier']} -> {tier}")
            counts[tier] = counts.get(tier, 0) + 1

            if args.write:
                project["tier"] = tier
                if match:
                    project["observed_name"] = match["name"]
                    project["observed_project_type"] = match.get("project_type")
                    project["mapped"] = match.get("geometry") is not None
                else:
                    for key in ("observed_name", "observed_project_type", "mapped"):
                        project.pop(key, None)

    print(json.dumps(counts, indent=2))
    for change in changes:
        print("  changed:", change)

    if args.write:
        document["measured_against"] = args.api
        document["measured_at"] = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
        document["measured_counts"] = counts
        PORTFOLIO.write_text(json.dumps(document, indent=2) + "\n")
        print(f"\nwrote {PORTFOLIO}")

    # A project falling out of "guaranteed" is the failure this exists to catch.
    regressions = [c for c in changes if "guaranteed ->" in c]
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
