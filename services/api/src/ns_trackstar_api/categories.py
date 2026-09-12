from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from ns_trackstar_api.area import normalize_lifecycle

router = APIRouter()
ConsumerCategory = Literal["development", "roads", "utilities", "places"]
CategoryBasis = Literal["project_type", "official_subtype", "name_fallback", "default"]

ROAD_TERMS = (
    "road",
    "roads",
    "street",
    "streets",
    "avenue",
    "avenues",
    "boulevard",
    "boulevards",
    "highway",
    "highways",
    "bridge",
    "bridges",
    "overcrossing",
    "overcrossings",
    "interchange",
    "interchanges",
    "intersection",
    "intersections",
    "pavement",
    "paving",
    "sidewalk",
    "sidewalks",
    "bicycle",
    "bike",
    "pedestrian",
    "traffic",
    "transit",
    "corridor",
    "corridors",
    "signal",
    "signals",
)
UTILITY_TERMS = (
    "water",
    "sewer",
    "stormwater",
    "storm water",
    "drain",
    "drains",
    "drainage",
    "storm drain",
    "storm drains",
    "flood",
    "pump station",
    "pump stations",
    "pipeline",
    "pipelines",
    "water main",
    "water mains",
    "sewer main",
    "sewer mains",
    "reservoir",
    "reservoirs",
    "wastewater",
    "recycled water",
    "treatment plant",
    "treatment plants",
    "well",
    "wells",
    "levee",
    "levees",
    "utility",
    "utilities",
    "telecom",
    "telecommunications",
    "broadband",
)
PLACE_TERMS = (
    "park",
    "parks",
    "trail",
    "trails",
    "school",
    "schools",
    "library",
    "libraries",
    "civic",
    "community center",
    "community centers",
    "recreation",
    "playground",
    "playgrounds",
    "fire station",
    "fire stations",
    "police station",
    "police stations",
    "city hall",
    "facility",
    "facilities",
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
    "subdivisions",
    "development",
    "warehouse",
    "warehouses",
    "hotel",
    "hotels",
    "retail",
    "restaurant",
    "restaurants",
    "winery",
    "wineries",
    "vineyard",
    "vineyards",
)
SEMANTIC_FIELDS = ("source_project_type", "record_type", "application_type")


def _normalized(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _contains_term(value: str, terms: tuple[str, ...]) -> bool:
    padded = f" {value} "
    return any(f" {term} " in padded for term in terms)


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


async def _semantic_values(request: Request, project_id: UUID) -> list[str]:
    cursor = await request.app.state.db.execute(
        """
        SELECT DISTINCT ON (field, value)
          field,
          value #>> '{}' AS semantic_value,
          observed_at
        FROM assertion
        WHERE project_id = %(project_id)s
          AND field = ANY(%(semantic_fields)s)
          AND jsonb_typeof(value) = 'string'
        ORDER BY field, value, observed_at DESC
        """,
        {"project_id": project_id, "semantic_fields": list(SEMANTIC_FIELDS)},
    )
    rows = await cursor.fetchall()
    return [str(row["semantic_value"]) for row in rows if row["semantic_value"]]


@router.get("/projects/{project_id}/classification")
async def project_classification(request: Request, project_id: UUID) -> dict:
    """Return one canonical consumer classification contract for project UI surfaces."""

    cursor = await request.app.state.db.execute(
        """
        SELECT
          p.canonical_name,
          p.project_type,
          COALESCE(
            (SELECT jsonb_object_agg(dimension, value)
             FROM project_status_dimension psd
             WHERE psd.project_id = p.id),
            '{}'::jsonb
          ) AS statuses
        FROM project p
        WHERE p.id = %s
        """,
        (project_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")

    semantic_values = await _semantic_values(request, project_id)
    category, basis, category_evidence = normalize_consumer_category(
        project_type=str(row["project_type"]),
        semantic_values=semantic_values,
        project_name=str(row["canonical_name"]),
    )
    lifecycle_stage, lifecycle_dimension, lifecycle_value = normalize_lifecycle(row["statuses"] or {})

    return {
        "project_id": str(project_id),
        "consumer_category": category,
        "category_basis": basis,
        "category_evidence": category_evidence,
        "semantic_values": semantic_values,
        "lifecycle_stage": lifecycle_stage,
        "lifecycle_evidence": {
            "dimension": lifecycle_dimension,
            "value": lifecycle_value,
        },
        "statuses": row["statuses"] or {},
    }


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
