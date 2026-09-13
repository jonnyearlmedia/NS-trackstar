"""Jurisdiction coverage scorecard for the Trackstar service area.

Coverage is never counted in map dots. A jurisdiction is scored separately in each
source category, and the state is *derived* from the evidence the manifest declares
rather than asserted by hand, so the manifest cannot claim coverage that no production
source actually supports.

Derivation rules, strongest first:

``strong``   at least one recurring structured tracker for this jurisdiction and
             category, polled on a schedule.
``partial``  only wider regional feeds, single-project document sets, or reference
             data. Real evidence, but not a jurisdiction-wide inventory.
``blocked``  no production evidence and a documented access restriction upstream.
             Blocked is not a failure to try; it records that the legitimate public
             route does not currently yield records.
``missing``  no production evidence and no documented blocker. This is work to do.

A category with a documented blocker keeps that blocker visible even when partial
evidence exists, because partial cover from a rollup does not make the missing local
source any less missing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()

CoverageState = Literal["strong", "partial", "blocked", "missing"]
EvidenceScope = Literal["recurring_tracker", "regional_rollup", "project_specific", "reference"]

STATE_RANK: dict[str, int] = {"strong": 3, "partial": 2, "blocked": 1, "missing": 0}
_MANIFEST_FILENAME = "napa-solano.json"


def _repository_root() -> Path:
    # services/api/src/ns_trackstar_api/coverage.py -> repository root
    return Path(__file__).resolve().parents[4]


def manifest_path() -> Path:
    return _repository_root() / "config" / "coverage" / _MANIFEST_FILENAME


def _config_keys(directory: str) -> set[str]:
    root = _repository_root() / "config" / directory
    keys: set[str] = set()
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        key = payload.get("key")
        if isinstance(key, str):
            keys.add(key)
    return keys


@lru_cache(maxsize=1)
def production_source_keys() -> frozenset[str]:
    return frozenset(_config_keys("sources"))


@lru_cache(maxsize=1)
def smoke_source_keys() -> frozenset[str]:
    return frozenset(_config_keys("smoke"))


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    return json.loads(manifest_path().read_text())


@dataclass(frozen=True, slots=True)
class CategoryCoverage:
    jurisdiction: str
    jurisdiction_name: str
    county: str
    category: str
    category_title: str
    state: CoverageState
    production_sources: tuple[str, ...]
    unpromoted_sources: tuple[str, ...]
    scopes: tuple[str, ...]
    roles: tuple[str, ...]
    limitation: str | None
    blocker: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "jurisdiction": self.jurisdiction,
            "jurisdiction_name": self.jurisdiction_name,
            "county": self.county,
            "category": self.category,
            "category_title": self.category_title,
            "state": self.state,
            "production_sources": list(self.production_sources),
            "unpromoted_sources": list(self.unpromoted_sources),
            "scopes": list(self.scopes),
            "roles": list(self.roles),
            "limitation": self.limitation,
            "blocker": self.blocker,
        }


# Spatial truth is the one category where reference layers *are* the deliverable.
# A jurisdiction is only strong there once Trackstar can place a record on a parcel,
# resolve it to an address, and say which jurisdiction it falls in.
SPATIAL_ROLES_FOR_STRONG = frozenset({"parcels", "address_level", "boundaries"})


def derive_state(
    *,
    scopes: tuple[str, ...],
    has_blocker: bool,
    category: str | None = None,
    roles: tuple[str, ...] = (),
) -> CoverageState:
    if "recurring_tracker" in scopes:
        return "strong"
    if category == "gis_spatial" and SPATIAL_ROLES_FOR_STRONG.issubset(set(roles)):
        return "strong"
    if scopes:
        return "partial"
    return "blocked" if has_blocker else "missing"


def _category_coverage(
    *,
    jurisdiction: dict[str, Any],
    category_key: str,
    category_title: str,
    production: frozenset[str],
    smoke: frozenset[str],
) -> CategoryCoverage:
    entry = (jurisdiction.get("categories") or {}).get(category_key) or {}
    evidence = entry.get("evidence") or []

    production_sources: list[str] = []
    unpromoted: list[str] = []
    scopes: list[str] = []
    roles: list[str] = []
    for item in evidence:
        source_key = str(item.get("source") or "")
        scope = str(item.get("scope") or "")
        role = str(item.get("role") or "")
        if not source_key:
            continue
        if source_key in production:
            production_sources.append(source_key)
            if scope and scope not in scopes:
                scopes.append(scope)
            if role and role not in roles:
                roles.append(role)
        else:
            # Declared but not promoted. It is never allowed to raise the state.
            unpromoted.append(source_key)

    blocker = entry.get("blocker")
    if isinstance(blocker, dict):
        smoke_source = blocker.get("smoke_source")
        if isinstance(smoke_source, str) and smoke_source in smoke and smoke_source not in unpromoted:
            unpromoted.append(smoke_source)
    else:
        blocker = None

    return CategoryCoverage(
        jurisdiction=str(jurisdiction["key"]),
        jurisdiction_name=str(jurisdiction["name"]),
        county=str(jurisdiction["county"]),
        category=category_key,
        category_title=category_title,
        state=derive_state(
            scopes=tuple(scopes),
            has_blocker=blocker is not None,
            category=category_key,
            roles=tuple(roles),
        ),
        production_sources=tuple(sorted(set(production_sources))),
        unpromoted_sources=tuple(sorted(set(unpromoted))),
        scopes=tuple(scopes),
        roles=tuple(roles),
        limitation=entry.get("limitation"),
        blocker=blocker,
    )


def build_scorecard() -> dict[str, Any]:
    manifest = load_manifest()
    production = production_source_keys()
    smoke = smoke_source_keys()
    categories = manifest["categories"]

    jurisdictions: list[dict[str, Any]] = []
    totals: dict[str, int] = {"strong": 0, "partial": 0, "blocked": 0, "missing": 0}

    for jurisdiction in manifest["jurisdictions"]:
        rows = [
            _category_coverage(
                jurisdiction=jurisdiction,
                category_key=str(category["key"]),
                category_title=str(category["title"]),
                production=production,
                smoke=smoke,
            )
            for category in categories
        ]
        for row in rows:
            totals[row.state] += 1
        strong = sum(1 for row in rows if row.state == "strong")
        partial = sum(1 for row in rows if row.state == "partial")
        jurisdictions.append(
            {
                "key": jurisdiction["key"],
                "name": jurisdiction["name"],
                "county": jurisdiction["county"],
                "kind": jurisdiction["kind"],
                # A jurisdiction score is a plain fraction of categories that hold up.
                # Partial counts as half, because half-covered is not covered.
                "score": round((strong + partial * 0.5) / len(categories), 3),
                "categories": [row.to_dict() for row in rows],
            }
        )

    return {
        "service_area": manifest["service_area"],
        "categories": categories,
        "jurisdictions": jurisdictions,
        "totals": totals,
        "production_source_count": len(production),
        "unpromoted_source_count": len(smoke),
    }


def coverage_gaps(minimum_state: CoverageState = "partial") -> list[dict[str, Any]]:
    """Every jurisdiction/category that does not yet reach ``minimum_state``."""

    threshold = STATE_RANK[minimum_state]
    scorecard = build_scorecard()
    return [
        row
        for jurisdiction in scorecard["jurisdictions"]
        for row in jurisdiction["categories"]
        if STATE_RANK[row["state"]] < threshold
    ]


@router.get("/coverage/service-area")
async def service_area_coverage(request: Request) -> dict:
    """Public contract: what Trackstar claims to cover, and how honestly."""

    scorecard = build_scorecard()
    return {
        "service_area": scorecard["service_area"],
        "jurisdictions": [
            {
                "key": jurisdiction["key"],
                "name": jurisdiction["name"],
                "county": jurisdiction["county"],
                "score": jurisdiction["score"],
            }
            for jurisdiction in scorecard["jurisdictions"]
        ],
    }


@router.get("/admin/coverage")
async def admin_coverage(
    request: Request,
    jurisdiction: Annotated[str | None, Query()] = None,
) -> dict:
    """Full internal scorecard: which source categories remain incomplete, and why."""

    scorecard = build_scorecard()
    if jurisdiction is not None:
        matches = [
            item for item in scorecard["jurisdictions"] if item["key"] == jurisdiction
        ]
        if not matches:
            raise HTTPException(status_code=404, detail="Unknown jurisdiction")
        scorecard["jurisdictions"] = matches
    return scorecard


@router.get("/admin/coverage/gaps")
async def admin_coverage_gaps(request: Request) -> list[dict]:
    return coverage_gaps()
