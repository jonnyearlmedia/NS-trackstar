#!/usr/bin/env python3
"""Regenerate the coverage grid in docs/ROADMAP_COVERAGE.md from the manifest.

The grid used to be typed by hand while the totals under it were computed from
`config/coverage/napa-solano.json`. That is how it drifted: the table showed CEQA as
covered in all fourteen jurisdictions while the scorecard had always derived it as
partial. A hand-maintained summary of a computed thing will always drift, and it will
drift in the flattering direction.

    ./scripts/coverage-grid.py            # print the grid
    ./scripts/coverage-grid.py --write    # rewrite the block in the roadmap
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "services/api/src"))

from ns_trackstar_api.coverage import build_scorecard

ROADMAP = pathlib.Path(__file__).resolve().parent.parent / "docs/ROADMAP_COVERAGE.md"
COLUMNS = [
    ("dev", "current_development", 7),
    ("permit", "permits", 7),
    ("meet", "government_meetings", 6),
    ("cip", "cip_construction", 6),
    ("gis", "gis_spatial", 6),
    ("ceqa", "ceqa_environmental", 5),
    ("biz", "business_openings", 5),
    ("proc", "procurement", 0),
]
SYMBOL = {"strong": "OK", "partial": "~~", "blocked": "XX", "missing": "--"}
SHORT_NAME = {
    "City of Napa": "Napa",
    "Unincorporated Napa County": "Napa County (uninc)",
    "Unincorporated Solano County": "Solano County (uninc)",
}


def grid() -> str:
    scorecard = build_scorecard()
    lines = ["                        dev  permit  meet   cip   gis  ceqa  biz  proc"]
    for jurisdiction in scorecard["jurisdictions"]:
        label = SHORT_NAME.get(jurisdiction["name"], jurisdiction["name"])
        states = {row["category"]: row["state"] for row in jurisdiction["categories"]}
        line = f"{label:<24}"
        for _, key, width in COLUMNS:
            cell = SYMBOL[states.get(key, "missing")]
            line += f"{cell:<{width}}" if width else cell
        lines.append(line.rstrip())
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    rendered = grid()
    if not args.write:
        print(rendered)
        return 0

    text = ROADMAP.read_text()
    start = text.index("                        dev  permit")
    end = text.index("```", start)
    text = text[:start] + rendered + "\n" + text[end:]

    totals = build_scorecard()["totals"]
    text = re.sub(
        r"Derived totals, [^:]+: \*\*\d+ strong, \d+ partial, \d+ blocked,\n\d+ missing\*\*",
        f"Derived totals, September 13, 2026: **{totals['strong']} strong, "
        f"{totals['partial']} partial, {totals['blocked']} blocked,\n{totals['missing']} missing**",
        text,
    )
    ROADMAP.write_text(text)
    print(rendered)
    print("\nwrote", ROADMAP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
