from __future__ import annotations

from collections.abc import Callable

from ns_trackstar.adapters.arcgis import ArcGISRestAdapter
from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.adapters.ceqanet import CeqanetAdapter
from ns_trackstar.adapters.civicclerk import CivicClerkAdapter
from ns_trackstar.adapters.etrakit import ETrakitAdapter
from ns_trackstar.adapters.legistar import LegistarAdapter
from ns_trackstar.adapters.pdf_project_tracker import PdfProjectTrackerAdapter

AdapterFactory = Callable[[SourceConfig], CollectorAdapter]

ADAPTERS: dict[str, AdapterFactory] = {
    "arcgis_rest": ArcGISRestAdapter,
    "civicclerk": CivicClerkAdapter,
    "ceqanet": CeqanetAdapter,
    "etrakit": ETrakitAdapter,
    "legistar": LegistarAdapter,
    "pdf_project_tracker": PdfProjectTrackerAdapter,
}


def build_adapter(adapter_name: str, config: SourceConfig) -> CollectorAdapter:
    try:
        factory = ADAPTERS[adapter_name]
    except KeyError as exc:
        raise ValueError(f"Unknown adapter: {adapter_name}") from exc
    return factory(config)
