"""Reusable source-platform adapters."""

from ns_trackstar.adapters.arcgis import ArcGISRestAdapter
from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.adapters.civicclerk import CivicClerkAdapter
from ns_trackstar.adapters.etrakit import ETrakitAdapter
from ns_trackstar.adapters.legistar import LegistarAdapter

__all__ = [
    "ArcGISRestAdapter",
    "CivicClerkAdapter",
    "CollectorAdapter",
    "ETrakitAdapter",
    "LegistarAdapter",
    "SourceConfig",
]
