from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SourceHealthState(StrEnum):
    HEALTHY = "healthy"
    DELAYED = "delayed"
    DEGRADED = "degraded"
    BROKEN = "broken"
    BLOCKED = "blocked"
    SCHEMA_CHANGED = "schema_changed"
    DISABLED = "disabled"


class LocationAccuracy(StrEnum):
    EXACT_SOURCE_GEOMETRY = "exact_source_geometry"
    EXACT_PARCEL = "exact_parcel"
    EXACT_ADDRESS = "exact_address"
    INTERSECTION = "intersection"
    STREET_SEGMENT = "street_segment"
    APPROXIMATE_AREA = "approximate_area"
    CITY_ONLY = "city_only"


class RelationshipType(StrEnum):
    SAME_PHYSICAL_PROJECT = "same_physical_project"
    PARENT_CHILD = "parent_child"
    ALIAS_OF = "alias_of"
    SUPERSEDES = "supersedes"
    RELATED_INFRASTRUCTURE = "related_infrastructure"
    PERMIT_FOR = "permit_for"
    ENVIRONMENTAL_REVIEW_FOR = "environmental_review_for"
    LITIGATION_ABOUT = "litigation_about"
    BUSINESS_WITHIN = "business_within"
    SPATIAL_OVERLAP_ONLY = "spatial_overlap_only"
    ADJACENT_PROJECT = "adjacent_project"


class NormalizedRecord(BaseModel):
    source_key: str
    external_id: str
    canonical_url: str | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    normalized_payload: dict[str, Any] = Field(default_factory=dict)
    geometry_geojson: dict[str, Any] | None = None
    geometry_source: str | None = None
    location_accuracy: LocationAccuracy | None = None


class CollectorResult(BaseModel):
    records: list[NormalizedRecord] = Field(default_factory=list)
    schema_fingerprint: str | None = None
    parser_yield: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
