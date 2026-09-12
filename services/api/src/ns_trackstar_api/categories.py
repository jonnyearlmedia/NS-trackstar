from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

router = APIRouter()
ConsumerCategory = Literal["development", "roads", "utilities", "places"]
CategoryBasis = Literal["project_type", "official_subtype", "name_fallback", "default"]

ROAD_TERMS = (
    "road",
    "street",
    "avenue",
    "boulevard",
    "highway",
    "bridge",
    "overcrossing",
    "interchange",
    "intersection",
    "pavement",
    "paving",
    "sidewalk",
    "bicycle",
    "bike",
    "pedestrian",
    "traffic",
    "transit",
    "corridor",
    "signal",
)
UTILITY_TERMS = (
    "water",
    "sewer",
    "stormwater",
    "storm water",
    "drainage",
    "storm drain",
    "flood",
    "pump station",
    "pipeline",
    "water main",
    "sewer main",
    "reservoir",
    "wastewater",
    "recycled water",
    "treatment plant",
    "well",
    "levee",
    "utility",
    "utilities",
    "telecom",
    "telecommunications",
    "broadband",
)
PLACE_TERMS = (
    "park",
    "trail",
    "school",
    "library",
    "civic",
    "community center",
    "recreation",
    "playground",
    "fire station",
    "police station",
    "city hall",
    "public facility",
    "public facilities",
)
DEVELOPMENT_TERMS = (
    "residential",
    "housing",
    "commercial",
    "industrial",
    "mixed use",
    "mixed-use",
    "subdivision",
    "development",
    "warehouse",
    "hotel",
    "retail",
    "restaurant",
    "winery",
)
SEMANTIC_FIELDS = ("source_project_type", "record_type", "application_type")


def _normalized(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _contains_term(value: str, terms: tuple[str, ...]) -> bool:
    padded = f" {value} "
    return any(f" {term} " in padded or value.startswith(f"{term} ") or value.endswith(f" {term}") for term in terms)


def _category_from_text(value: str) -> ConsumerCategory | None:
    normalized = _normalized(value)
    if _contains_term(normalized, UTILITY_TERMS):
        return "utilities"
    if _contains_term(normalized, ROAD_TERMS):
        return "roads"
    if _contains_term(normalized, PLACE_TERMS):
        return "places"
    if _contains_term(normalized, DEVELOPMENT_TERMS):
        return "development"
    return None


def normalize_consumer_category(
    *,
    project_type: str,
    semantic_values: list[str],
    project_name: str,
) -> tuple[ConsumerCategory, CategoryBasis, str | None]:
    """Map internal records to broad resident-facing categories conservatively.

    Structured official subtype values outrank name inference. Project type remains
    authoritative for purpose-built transportation and water records. Broad
    ``public_works`` records are not automatically treated as public places.
    """

    normalized_type = _normalized(project_type)
    if normalized_type == "transportation project":
        return "roads", "project_type", project_type
    if normalized_type == "water infrastructure":
        return "utilities", "project_type", project_type

    for value in semantic_values:
        category = _category_from_text(value)
        if category is not None:
            return category, "official_subtype", value

    if normalized_type == "municipal development":
        return "development", "project_type", project_type

    name_category = _category_from_text(project_name)
    if name_category is not None:
        return name_category, "name_fallback", project_name

    if normalized_type == "public works":
        # Unknown public works should stay in a general public-place bucket only as a
        # last resort until stronger source subtype evidence is available.
        return "places", "default", project_type

    return "development", "default", project_type


@router.get("/map/category-truth")
async def category_truth(
    request: Request,
    west: Annotated[float, Query(ge=-180, le=180)],
    south: Annotated[float, Query(ge=-90, le=90)],
    east: Annotated[float, Query(ge=-180, le=180)],
    north: Annotated[float, Query(ge=-90, le=90)],
) -> list[dict]:
    if west >= east or south >= north:
        return []

    cursor = await request.app.state.db.execute(
        """
        SELECT
          p.id,
          p.canonical_name,
          p.project_type,
          a.field,
          a.value #>> '{}' AS semantic_value,
          a.observed_at
        FROM project p
        LEFT JOIN assertion a
          ON a.project_id = p.id
         AND a.field = ANY(%(semantic_fields)s)
         AND jsonb_typeof(a.value) = 'string'
        WHERE p.primary_geometry IS NOT NULL
          AND p.primary_geometry && ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)
        ORDER BY p.id, a.observed_at DESC NULLS LAST
        """,
        {
            "west": west,
            "south": south,
            "east": east,
            "north": north,
            "semantic_fields": list(SEMANTIC_FIELDS),
        },
    )
    rows = await cursor.fetchall()

    grouped: dict[object, dict] = {}
    values: dict[object, list[str]] = defaultdict(list)
    for row in rows:
        grouped.setdefault(
            row["id"],
            {
                "id": str(row["id"]),
                "name": row["canonical_name"],
                "project_type": row["project_type"],
            },
        )
        semantic_value = row["semantic_value"]
        if semantic_value and str(semantic_value) not in values[row["id"]]:
            values[row["id"]].append(str(semantic_value))

    response: list[dict] = []
    for project_id, project in grouped.items():
        category, basis, evidence = normalize_consumer_category(
            project_type=str(project["project_type"]),
            semantic_values=values.get(project_id, []),
            project_name=str(project["name"]),
        )
        response.append(
            {
                **project,
                "consumer_category": category,
                "category_basis": basis,
                "category_evidence": evidence,
                "semantic_values": values.get(project_id, []),
            }
        )
    return response
