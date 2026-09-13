"""Deterministic consumer narrative composed from structured project evidence.

Trackstar answers four questions for a normal resident, in this order:

1. What is this?
2. What is happening now?
3. Why would I care?
4. What happens next?

Everything here is a pure function over evidence Trackstar already holds. No model
call is required to produce an ordinary project explanation, and nothing is invented:
every sentence is traceable to an assertion, a status dimension or a project event.
When the evidence genuinely does not support a claim the composer says less rather
than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, date, datetime
from typing import Any, Literal

ConsumerCategory = Literal["development", "roads", "utilities", "places"]

# Identifiers, case numbers and internal codes are real evidence but they are never
# the answer to "what is this?". They stay available under secondary detail sections.
BUREAUCRATIC_FIELDS = frozenset(
    {
        "apn",
        "building_california_project_id",
        "caltrans_district",
        "implementing_agency_id",
        "planning_case",
        "planning_cases",
        "program_code",
        "project_number",
        "record_type",
        "sch_number",
    }
)

_PROJECT_TYPE_NOUNS: dict[str, str] = {
    "municipal_development": "development project",
    "transportation_project": "road or transit project",
    "water_infrastructure": "water or sewer project",
    "public_works": "public works project",
    "environmental_review": "environmental review",
    "business_opening": "business",
}

_CATEGORY_NOUNS: dict[str, str] = {
    "development": "development project",
    "roads": "road or transit project",
    "utilities": "utility project",
    "places": "public facility project",
}

_LIFECYCLE_SENTENCES: dict[str, str] = {
    "proposed": "It has been proposed but not yet approved.",
    "review": "It is going through official review right now.",
    "approved": "It has been approved and is waiting to be built.",
    "construction": "It is being built right now.",
    "completed": "The work here is finished.",
    "inactive": "It is not moving forward at the moment.",
}

_NEXT_STEP_LABELS: dict[str, str] = {
    "planned_completion": "Planned completion",
    "completion_date": "Expected completion",
    "planned_construction_start": "Construction expected to start",
    "construction_start": "Construction starts",
    "expected_start_date": "Work expected to start",
    "planned_start": "Work planned to start",
    "construction_year": "Construction year",
    "design_year": "Design year",
    "fiscal_year": "Scheduled fiscal year",
}

# Ordered: the first supported next step wins, nearest-term first.
_NEXT_STEP_ORDER: tuple[str, ...] = (
    "planned_construction_start",
    "construction_start",
    "expected_start_date",
    "planned_start",
    "planned_completion",
    "completion_date",
    "construction_year",
    "design_year",
    "fiscal_year",
)

_LIFECYCLE_NEXT_STEP: dict[str, str] = {
    "proposed": "Official review and public hearings.",
    "review": "A decision from the city or county after review is complete.",
    "approved": "Permitting and pre-construction work.",
    "construction": "Construction continues until the work is finished.",
}

_EVIDENCE_SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "scale",
        "Size and scope",
        (
            "residential_units",
            "units",
            "project_units",
            "unit_count_or_square_footage",
            "building_area_sqft",
            "site_acres",
            "location_acres",
            "length_miles",
            "development_type",
            "improvement_type",
            "source_project_type",
        ),
    ),
    (
        "location",
        "Where it is",
        ("address", "location_description", "city", "county", "zoning",
         "land_use_designation", "state_highways"),
    ),
    (
        "people",
        "Who is behind it",
        (
            "applicant",
            "owner_applicant",
            "developer",
            "business_name",
            "implementing_agency",
            "lead_agency",
            "project_manager",
            "planner",
        ),
    ),
    (
        "schedule",
        "Schedule",
        (
            "application_submitted_at",
            "expected_start_date",
            "planned_construction_start",
            "construction_start",
            "planned_start",
            "design_year",
            "construction_year",
            "planned_completion",
            "completion_date",
            "fiscal_year",
            "public_hearings",
        ),
    ),
    (
        "money",
        "Cost and funding",
        (
            "estimated_cost",
            "total_cost",
            "funding",
            "budget_fund",
            "sb1_funding",
            "iija_funding",
            "is_sb1",
            "is_iija",
        ),
    ),
    (
        "approvals",
        "Permits and approvals",
        (
            "official_status_text",
            "official_status_date",
            "application_type",
            "local_action",
            "appeal",
            "variance_required",
            "viewshed_exception",
            "right_of_way_status",
            "utility_relocation_status",
            "environmental_clearance_status",
        ),
    ),
    (
        "environmental",
        "Environmental review",
        (
            "latest_environmental_document_type",
            "latest_environmental_document_title",
            "latest_environmental_document_received",
        ),
    ),
    (
        "identifiers",
        "Official identifiers",
        (
            "planning_case",
            "planning_cases",
            "project_number",
            "apn",
            "sch_number",
            "record_type",
            "program_code",
            "building_california_project_id",
            "implementing_agency_id",
            "caltrans_district",
        ),
    ),
)

_FIELD_LABELS: dict[str, str] = {
    "apn": "Assessor parcel number",
    "address": "Address",
    "application_submitted_at": "Application filed",
    "application_type": "Application type",
    "appeal": "Appeal",
    "budget_fund": "Budget fund",
    "building_area_sqft": "Building area",
    "building_california_project_id": "Building California project ID",
    "business_name": "Business",
    "caltrans_district": "Caltrans district",
    "city": "City",
    "completion_date": "Expected completion",
    "construction_start": "Construction start",
    "construction_year": "Construction year",
    "county": "County",
    "design_year": "Design year",
    "developer": "Developer",
    "development_type": "Development type",
    "environmental_clearance_status": "Environmental clearance",
    "estimated_cost": "Estimated cost",
    "expected_start_date": "Expected start",
    "fiscal_year": "Fiscal year",
    "funding": "Funding",
    "iija_funding": "Federal IIJA funding",
    "implementing_agency": "Implementing agency",
    "implementing_agency_id": "Implementing agency ID",
    "improvement_type": "Improvement type",
    "is_iija": "Federally funded (IIJA)",
    "is_sb1": "State funded (SB 1)",
    "land_use_designation": "Land use designation",
    "latest_environmental_document_received": "Latest environmental filing",
    "latest_environmental_document_title": "Environmental document",
    "latest_environmental_document_type": "Environmental document type",
    "lead_agency": "Lead agency",
    "length_miles": "Length",
    "local_action": "Local action",
    "location_acres": "Site size",
    "location_description": "Location",
    "official_status_date": "Status date",
    "official_status_text": "Official status",
    "owner_applicant": "Owner or applicant",
    "planned_completion": "Planned completion",
    "planned_construction_start": "Construction planned to start",
    "planned_start": "Planned start",
    "planner": "Case planner",
    "planning_case": "Planning case",
    "planning_cases": "Planning cases",
    "program_code": "Program code",
    "project_manager": "Project manager",
    "project_number": "Project number",
    "public_hearings": "Public hearings",
    "record_type": "Record type",
    "residential_units": "Homes",
    "right_of_way_status": "Right of way",
    "sb1_funding": "State SB 1 funding",
    "sch_number": "State Clearinghouse number",
    "site_acres": "Site size",
    "source_project_type": "Project type",
    "state_highways": "State highways",
    "total_cost": "Total cost",
    "units": "Units",
    "unit_count_or_square_footage": "Size",
    "utility_relocation_status": "Utility relocation",
    "variance_required": "Variance required",
    "viewshed_exception": "Viewshed exception",
    "zoning": "Zoning",
}

# Source authority for the one sentence that leads the answer. A statewide or federal
# rollup describes the *filing*, not the project: a CEQA amendment abstract once made
# Napa Pipe read as a bridge project. Those descriptions are still shown, but a local
# agency's own description outranks them, and a rollup abstract never leads alone.
ROLLUP_DESCRIPTION_SOURCES = (
    "california.ceqanet",
    "federal-register",
    "courtlistener",
    "caltrans.building-ca",
    "bia.",
    "nigc.",
)

_UNIT_FIELDS = ("residential_units", "units", "project_units")
# Some agencies publish scale as one string rather than as separate fields. Vallejo's
# development tracker writes "179,688 square feet 178 single-family" in a single cell,
# which is two facts wearing one label. Read naively it makes the Costco project
# 179,688 homes; ignored, it leaves "why you'd care" blank on the most-searched
# project in the city. So combined fields are split into their real quantities.
_COMBINED_SCALE_FIELDS = ("unit_count_or_square_footage", "units_or_square_feet", "size")
_ACRE_FIELDS = ("site_acres", "location_acres")
_COST_FIELDS = ("estimated_cost", "total_cost", "funding")


@dataclass(frozen=True, slots=True)
class Fact:
    """One consumer-facing statement with the evidence that backs it."""

    label: str
    value: str
    field: str
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class Explainer:
    what_is_this: str
    whats_happening: str | None
    whats_happening_at: str | None
    why_care: list[Fact]
    whats_next: str | None
    whats_next_basis: str | None
    evidence_backed: bool
    basis: list[str] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "what_is_this": self.what_is_this,
            "whats_happening": self.whats_happening,
            "whats_happening_at": self.whats_happening_at,
            "why_care": [
                {
                    "label": fact.label,
                    "value": fact.value,
                    "field": fact.field,
                    "source_url": fact.source_url,
                }
                for fact in self.why_care
            ],
            "whats_next": self.whats_next,
            "whats_next_basis": self.whats_next_basis,
            "evidence_backed": self.evidence_backed,
            "basis": list(self.basis),
        }


def field_label(field_name: str) -> str:
    return _FIELD_LABELS.get(field_name, field_name.replace("_", " ").capitalize())


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(part for part in (_text(item) for item in value) if part)
    if isinstance(value, dict):
        return ", ".join(
            f"{key.replace('_', ' ')}: {_text(item)}" for key, item in value.items() if item
        )
    return " ".join(str(value).split())


def _number(value: float) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.1f}"


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip()
        # "245 units", "1.4 miles" and "approx. 30 acres" all carry a usable number.
        digits = ""
        seen_digit = False
        for character in cleaned:
            if character.isdigit() or (character == "." and seen_digit and "." not in digits):
                digits += character
                seen_digit = True
            elif seen_digit:
                break
        if digits and digits != ".":
            try:
                return float(digits)
            except ValueError:
                return None
    return None



# Words an agency uses for each kind of quantity, longest first so "square feet" wins
# over "feet". Only these three are read: a number whose unit is not recognised is left
# alone rather than guessed at, because a wrong unit on a scale fact is worse than none.
_SCALE_UNITS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "building_area_sqft",
        ("square feet", "square foot", "sq. ft", "sq ft", "sqft", "s.f.", "sf"),
    ),
    (
        "residential_units",
        (
            "single-family",
            "single family",
            "multifamily",
            "multi-family",
            "dwelling units",
            "dwelling",
            "residential units",
            "apartments",
            "townhomes",
            "condos",
            "homes",
            "units",
            "sfd",
            "sfr",
        ),
    ),
    ("site_acres", ("acres", "acre")),
)


def _split_combined_scale(value: Any) -> dict[str, float]:
    """Pull each quantity out of a single cell that carries more than one.

    "179,688 square feet 178 single-family" is two facts. Each number is attributed to
    the unit word that follows it, and a number whose unit is not recognised is dropped
    rather than assigned to whichever field happens to be first.
    """

    text = _text(value)
    if not text:
        return {}
    found: dict[str, float] = {}
    for match in re.finditer(r"([\d,]+(?:\.\d+)?)\s*([A-Za-z.\- ]{0,24})", text):
        number = _numeric(match.group(1))
        if number is None or number <= 0:
            continue
        trailing = match.group(2).strip().lower()
        if not trailing:
            continue
        for field, words in _SCALE_UNITS:
            if any(trailing.startswith(word) for word in words) and field not in found:
                found[field] = number
                break
    return found


def _money(value: Any) -> str | None:
    amount = _numeric(value)
    if amount is None or amount <= 0:
        return None
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.1f}".rstrip("0").rstrip(".") + " billion"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}".rstrip("0").rstrip(".") + " million"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}"


def _sentence(text: str) -> str:
    clean = " ".join(str(text or "").split())
    if not clean:
        return ""
    if clean[-1] not in ".!?":
        clean = f"{clean}."
    return clean[0].upper() + clean[1:]


def _clip(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    cut = clean[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return f"{cut.rstrip(' ,;:')}…"


def _reads_like_prose(text: str) -> bool:
    """A usable description is a sentence, not a code, a label or a bare address."""

    clean = " ".join(str(text or "").split())
    if len(clean) < 40:
        return False
    if clean.count(" ") < 6:
        return False
    letters = sum(1 for character in clean if character.isalpha())
    return letters >= len(clean) * 0.55


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _format_date(value: Any) -> str | None:
    moment = _as_date(value)
    if moment is None:
        return _text(value) or None
    return moment.strftime("%B %-d, %Y")


def _month_year(value: Any) -> str | None:
    moment = _as_date(value)
    if moment is None:
        return _format_date(value)
    return moment.strftime("%B %Y")


class _Evidence:
    """Latest value per assertion field, with the URL that backs it."""

    def __init__(self, assertions: list[dict[str, Any]]) -> None:
        self._values: dict[str, Any] = {}
        self._urls: dict[str, str | None] = {}
        self._order: list[str] = []
        self._descriptions: list[tuple[str, str]] = []
        # Callers pass assertions newest first; keep the first value seen per field.
        for assertion in assertions:
            name = str(assertion.get("field") or "").strip()
            value = assertion.get("value")
            if not name or value is None or _text(value) == "":
                continue
            if name == "description":
                self._descriptions.append(
                    (_text(value), str(assertion.get("source_key") or ""))
                )
            if name in self._values:
                continue
            self._values[name] = value
            self._urls[name] = assertion.get("source_url")
            self._order.append(name)

    def descriptions(self) -> list[tuple[str, str]]:
        """Every description candidate, newest first, with its source key."""

        return list(self._descriptions)

    def __contains__(self, name: object) -> bool:
        return name in self._values

    def get(self, *names: str) -> Any:
        for name in names:
            if name in self._values:
                return self._values[name]
        return None

    def field_for(self, *names: str) -> str | None:
        for name in names:
            if name in self._values:
                return name
        return None

    def url(self, name: str) -> str | None:
        return self._urls.get(name)

    def fields(self) -> list[str]:
        return list(self._order)


def _identity_noun(
    *,
    evidence: _Evidence,
    project_type: str,
    consumer_category: str | None,
) -> str:
    explicit = evidence.get("development_type", "source_project_type", "improvement_type")
    explicit_text = _text(explicit).strip().lower()
    if explicit_text and 3 <= len(explicit_text) <= 60:
        return explicit_text.replace("_", " ")
    if project_type in _PROJECT_TYPE_NOUNS:
        return _PROJECT_TYPE_NOUNS[project_type]
    if consumer_category in _CATEGORY_NOUNS:
        return _CATEGORY_NOUNS[consumer_category]
    return "project"


def _ranked_descriptions(evidence: _Evidence) -> tuple[str | None, str | None]:
    """Split description candidates into local-agency prose and rollup-filing prose."""

    local: str | None = None
    rollup: str | None = None
    for value, source_key in evidence.descriptions():
        if not _reads_like_prose(value):
            continue
        is_rollup = any(source_key.startswith(prefix) for prefix in ROLLUP_DESCRIPTION_SOURCES)
        if is_rollup:
            rollup = rollup or value
        else:
            local = local or value
    return local, rollup


def _identity_clause(evidence: _Evidence) -> str | None:
    """Whether structured evidence alone can say what this is."""

    scale = _scale_clause(evidence)
    place = _place_clause(evidence)
    if scale and place:
        return f"{scale} at {place}"
    return scale or place


def _scale_clause(evidence: _Evidence) -> str | None:
    parts: list[str] = []
    units = _numeric(evidence.get(*_UNIT_FIELDS))
    if units and units >= 1:
        homes = "home" if units == 1 else "homes"
        parts.append(f"{_number(units)} {homes}")
    area = _numeric(evidence.get("building_area_sqft"))
    if area and area >= 1:
        parts.append(f"{_number(area)} square feet of building space")
    length = _numeric(evidence.get("length_miles"))
    if length and length > 0:
        miles = "mile" if length == 1 else "miles"
        parts.append(f"{_number(length)} {miles} of work")
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _place_clause(evidence: _Evidence) -> str | None:
    address = _text(evidence.get("address")).strip()
    if address and len(address) <= 90:
        return address
    described = _text(evidence.get("location_description")).strip()
    if described and len(described) <= 120:
        return described
    city = _text(evidence.get("city")).strip()
    if city:
        return city
    return None


def _compose_what_is_this(
    *,
    name: str,
    project_type: str,
    consumer_category: str | None,
    lifecycle_stage: str | None,
    evidence: _Evidence,
    basis: list[str],
) -> tuple[str, bool]:
    """Prefer the agency's own description; otherwise build a sentence from facts."""

    local, rollup = _ranked_descriptions(evidence)
    sentences: list[str] = []
    evidence_backed = False

    if local:
        sentences.append(_sentence(_clip(local, 300)))
        basis.append("description")
        evidence_backed = True
    elif rollup and _identity_clause(evidence) is None:
        # Nothing local to lead with and no structured identity either. The filing
        # abstract is all Trackstar has, so use it rather than saying nothing.
        sentences.append(_sentence(_clip(rollup, 300)))
        basis.append("rollup_description")
        evidence_backed = True
    else:
        noun = _identity_noun(
            evidence=evidence, project_type=project_type, consumer_category=consumer_category
        )
        scale = _scale_clause(evidence)
        place = _place_clause(evidence)
        if scale:
            basis.append("scale")
        if place:
            basis.append("location")

        if scale and place:
            sentences.append(_sentence(f"A {noun} with {scale} at {place}"))
            evidence_backed = True
        elif scale:
            sentences.append(_sentence(f"A {noun} with {scale}"))
            evidence_backed = True
        elif place:
            sentences.append(_sentence(f"A {noun} at {place}"))
            evidence_backed = True
        else:
            sentences.append(_sentence(f"{name} is a {noun} tracked in official public records"))

        if rollup:
            # The abstract follows the identity sentence instead of replacing it, so a
            # reader learns what the project is before what the latest filing says.
            sentences.append(_sentence(_clip(rollup, 220)))
            basis.append("rollup_description")

    stage_sentence = _LIFECYCLE_SENTENCES.get(str(lifecycle_stage or ""))
    if stage_sentence:
        sentences.append(stage_sentence)
        basis.append("lifecycle")
        evidence_backed = True

    return " ".join(sentences), evidence_backed


def _compose_whats_happening(
    *,
    events: list[dict[str, Any]],
    statuses: dict[str, str],
    evidence: _Evidence,
    basis: list[str],
) -> tuple[str | None, str | None]:
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type == "project_discovered":
            continue
        headline = _text(event.get("summary")) or _text(event.get("title"))
        if not headline:
            continue
        basis.append("event")
        moment = event.get("occurred_at") or event.get("observed_at")
        when = _month_year(moment)
        text = _sentence(_clip(headline, 220))
        if when:
            text = f"{text[:-1]} ({when})." if text.endswith(".") else f"{text} ({when})."
        return text, _text(moment) or None

    official = _text(evidence.get("official_status_text"))
    if official:
        basis.append("official_status")
        when = _format_date(evidence.get("official_status_date"))
        text = _sentence(f"Official records list this as {official}")
        if when:
            text = f"{text[:-1]}, as of {when}."
        return text, _text(evidence.get("official_status_date")) or None

    for dimension in ("delivery_stage", "official_tracker_stage", "planning", "environmental"):
        value = _text(statuses.get(dimension))
        if value:
            basis.append("status")
            readable = value.replace("_", " ")
            label = dimension.replace("_", " ")
            return _sentence(f"The current official {label} is {readable}"), None

    return None, None


def _compose_why_care(*, evidence: _Evidence, consumer_category: str | None) -> list[Fact]:
    facts: list[Fact] = []

    def add(label: str, value: str | None, field_name: str) -> None:
        if value and not any(fact.field == field_name for fact in facts):
            facts.append(Fact(label, value, field_name, evidence.url(field_name)))

    combined_field = evidence.field_for(*_COMBINED_SCALE_FIELDS)
    combined = _split_combined_scale(evidence.get(*_COMBINED_SCALE_FIELDS))

    units = _numeric(evidence.get(*_UNIT_FIELDS)) or combined.get("residential_units")
    if units and units >= 1:
        unit_field = evidence.field_for(*_UNIT_FIELDS) or combined_field or "residential_units"
        add("New homes", f"{_number(units)} {'home' if units == 1 else 'homes'}", unit_field)

    area = _numeric(evidence.get("building_area_sqft")) or combined.get("building_area_sqft")
    if area and area >= 1:
        area_field = (
            "building_area_sqft" if "building_area_sqft" in evidence else combined_field
        ) or "building_area_sqft"
        add("Building space", f"{_number(area)} sq ft", area_field)

    acres = _numeric(evidence.get(*_ACRE_FIELDS)) or combined.get("site_acres")
    if acres and acres > 0:
        acre_field = evidence.field_for(*_ACRE_FIELDS) or combined_field or "site_acres"
        add("Site size", f"{_number(acres)} {'acre' if acres == 1 else 'acres'}", acre_field)

    length = _numeric(evidence.get("length_miles"))
    if length and length > 0:
        add("Length", f"{_number(length)} {'mile' if length == 1 else 'miles'}", "length_miles")

    for cost_field in _COST_FIELDS:
        money = _money(evidence.get(cost_field))
        if money:
            add(field_label(cost_field), money, cost_field)
            break

    business = _text(evidence.get("business_name"))
    if business:
        add("Business", business, "business_name")

    developer_field = evidence.field_for("developer", "owner_applicant", "applicant")
    if developer_field:
        developer = _text(evidence.get(developer_field))
        if developer and len(developer) <= 80:
            add(field_label(developer_field), developer, developer_field)

    if consumer_category == "roads":
        highways = _text(evidence.get("state_highways"))
        if highways:
            add("Highways affected", highways, "state_highways")

    return facts[:6]


def _compose_whats_next(
    *,
    evidence: _Evidence,
    lifecycle_stage: str | None,
    events: list[dict[str, Any]],
    now: datetime | None,
) -> tuple[str | None, str | None]:
    reference = _parse_moment(now) or datetime.now(UTC)
    for event in events:
        moment = event.get("occurred_at")
        parsed = _parse_moment(moment)
        if parsed is None or parsed <= reference:
            continue
        headline = _text(event.get("title")) or _text(event.get("summary"))
        if not headline:
            continue
        when = _format_date(moment)
        text = _sentence(_clip(headline, 180))
        return (f"{text[:-1]} on {when}." if when else text), "scheduled_event"

    for name in _NEXT_STEP_ORDER:
        raw = evidence.get(name)
        if raw is None:
            continue
        value = _format_date(raw) if "date" in name or "start" in name or "completion" in name else _text(raw)
        if not value:
            continue
        return _sentence(f"{_NEXT_STEP_LABELS.get(name, field_label(name))}: {value}"), name

    hearings = _text(evidence.get("public_hearings"))
    if hearings:
        return _sentence(f"Public hearings: {hearings}"), "public_hearings"

    generic = _LIFECYCLE_NEXT_STEP.get(str(lifecycle_stage or ""))
    if generic:
        return generic, "lifecycle_stage"
    return None, None


def _parse_moment(value: Any) -> datetime | None:
    """Normalize any published timestamp to UTC so comparisons are well defined."""

    if isinstance(value, datetime):
        moment = value
    else:
        text = _text(value)
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
    # A source that publishes a bare local timestamp is read as UTC rather than as the
    # collector host's zone, so the same record sorts the same way wherever it runs.
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def compose_explainer(
    *,
    name: str,
    project_type: str,
    consumer_category: str | None = None,
    lifecycle_stage: str | None = None,
    assertions: list[dict[str, Any]] | None = None,
    statuses: dict[str, str] | None = None,
    events: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> Explainer:
    """Compose the consumer answer without any model call.

    ``assertions`` must be ordered newest first and shaped like the project detail
    contract: ``{"field", "value", "source_url"}``. ``events`` must be ordered newest
    first with ``occurred_at``/``observed_at`` timestamps.
    """

    evidence = _Evidence(assertions or [])
    event_list = list(events or [])
    status_map = {str(key): str(value) for key, value in (statuses or {}).items() if value}
    basis: list[str] = []

    what_is_this, evidence_backed = _compose_what_is_this(
        name=name,
        project_type=project_type,
        consumer_category=consumer_category,
        lifecycle_stage=lifecycle_stage,
        evidence=evidence,
        basis=basis,
    )
    whats_happening, happening_at = _compose_whats_happening(
        events=event_list, statuses=status_map, evidence=evidence, basis=basis
    )
    why_care = _compose_why_care(evidence=evidence, consumer_category=consumer_category)
    if why_care:
        basis.append("why_care")
    whats_next, next_basis = _compose_whats_next(
        evidence=evidence, lifecycle_stage=lifecycle_stage, events=event_list, now=now
    )

    return Explainer(
        what_is_this=what_is_this,
        whats_happening=whats_happening,
        whats_happening_at=happening_at,
        why_care=why_care,
        whats_next=whats_next,
        whats_next_basis=next_basis,
        evidence_backed=evidence_backed or bool(why_care) or bool(whats_happening),
        basis=sorted(set(basis)),
    )


def compose_evidence_sections(
    assertions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Group every structured assertion into consumer-readable detail sections.

    Nothing is dropped. Fields Trackstar has no opinion about land in "Other details"
    rather than being hidden behind a hardcoded allowlist.
    """

    evidence = _Evidence(assertions or [])
    placed: set[str] = set()
    sections: list[dict[str, Any]] = []

    for key, title, fields in _EVIDENCE_SECTIONS:
        items = []
        for name in fields:
            if name in placed or name not in evidence:
                continue
            value = _text(evidence.get(name))
            if not value:
                continue
            placed.add(name)
            items.append(
                {
                    "field": name,
                    "label": field_label(name),
                    "value": value,
                    "source_url": evidence.url(name),
                    "bureaucratic": name in BUREAUCRATIC_FIELDS,
                }
            )
        if items:
            sections.append({"key": key, "title": title, "items": items})

    remaining = []
    for name in evidence.fields():
        if name in placed or name == "description":
            continue
        value = _text(evidence.get(name))
        if not value:
            continue
        remaining.append(
            {
                "field": name,
                "label": field_label(name),
                "value": value,
                "source_url": evidence.url(name),
                "bureaucratic": name in BUREAUCRATIC_FIELDS,
            }
        )
    if remaining:
        sections.append({"key": "other", "title": "Other details", "items": remaining})

    return sections
