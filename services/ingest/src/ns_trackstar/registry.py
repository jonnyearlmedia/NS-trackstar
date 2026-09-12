from __future__ import annotations

from collections.abc import Callable

from ns_trackstar.adapters.arcgis import ArcGISRestAdapter
from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.adapters.civicclerk import CivicClerkAdapter
from ns_trackstar.adapters.etrakit import ETrakitAdapter

AdapterFactory = Callable[[SourceConfig], CollectorAdapter]

ADAPTERS: dict[str, AdapterFactory] = {
    "arcgis_rest": ArcGISRestAdapter,
    "civicclerk": CivicClerkAdapter,
    "etrakit": ETrakitAdapter,
}


def build_adapter(adapter_name: str, config: SourceConfig) -> CollectorAdapter:
    try:
        factory = ADAPTERS[adapter_name]
    except KeyError as exc:
        raise ValueError(f"Unknown adapter: {adapter_name}") from exc
    return factory(config)
