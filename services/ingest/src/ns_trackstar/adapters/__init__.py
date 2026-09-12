"""Reusable source-platform adapters."""

from ns_trackstar.adapters.arcgis import ArcGISRestAdapter
from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.adapters.ceqanet import CeqanetAdapter
from ns_trackstar.adapters.civicclerk import CivicClerkAdapter
from ns_trackstar.adapters.courtlistener import CourtListenerAdapter
from ns_trackstar.adapters.etrakit import ETrakitAdapter
from ns_trackstar.adapters.legistar import LegistarAdapter
from ns_trackstar.adapters.pdf_project_tracker import PdfProjectTrackerAdapter
from ns_trackstar.adapters.transportation import BayArea511TrafficAdapter, WzdxAdapter

__all__ = [
    "ArcGISRestAdapter",
    "BayArea511TrafficAdapter",
    "CeqanetAdapter",
    "CivicClerkAdapter",
    "CollectorAdapter",
    "CourtListenerAdapter",
    "ETrakitAdapter",
    "LegistarAdapter",
    "PdfProjectTrackerAdapter",
    "SourceBlockedError",
    "SourceConfig",
    "WzdxAdapter",
]
