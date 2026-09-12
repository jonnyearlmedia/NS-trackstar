from __future__ import annotations

from collections.abc import Callable

from ns_trackstar.adapters.accela_aca import AccelaAcaAdapter
from ns_trackstar.adapters.arcgis import ArcGISRestAdapter
from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.adapters.ceqanet import CeqanetAdapter
from ns_trackstar.adapters.civicclerk import CivicClerkAdapter
from ns_trackstar.adapters.courtlistener import CourtListenerAdapter
from ns_trackstar.adapters.etrakit import ETrakitAdapter
from ns_trackstar.adapters.federal_register import FederalRegisterAdapter
from ns_trackstar.adapters.html_table import HtmlTableAdapter
from ns_trackstar.adapters.legistar import LegistarAdapter
from ns_trackstar.adapters.official_documents import OfficialDocumentSetAdapter
from ns_trackstar.adapters.opencities_map import OpenCitiesMapAdapter
from ns_trackstar.adapters.pdf_project_tracker import PdfProjectTrackerAdapter
from ns_trackstar.adapters.tabular_pdf_project_tracker import TabularPdfProjectTrackerAdapter
from ns_trackstar.adapters.transportation import BayArea511TrafficAdapter, WzdxAdapter

AdapterFactory = Callable[[SourceConfig], CollectorAdapter]

ADAPTERS: dict[str, AdapterFactory] = {
    "accela_aca": AccelaAcaAdapter,
    "arcgis_rest": ArcGISRestAdapter,
    "civicclerk": CivicClerkAdapter,
    "courtlistener": CourtListenerAdapter,
    "ceqanet": CeqanetAdapter,
    "etrakit": ETrakitAdapter,
    "federal_register": FederalRegisterAdapter,
    "html_table": HtmlTableAdapter,
    "legistar": LegistarAdapter,
    "opencities_map": OpenCitiesMapAdapter,
    "official_document_set": OfficialDocumentSetAdapter,
    "pdf_project_tracker": PdfProjectTrackerAdapter,
    "tabular_pdf_project_tracker": TabularPdfProjectTrackerAdapter,
    "bayarea_511_traffic": BayArea511TrafficAdapter,
    "wzdx": WzdxAdapter,
}


def build_adapter(adapter_name: str, config: SourceConfig) -> CollectorAdapter:
    try:
        factory = ADAPTERS[adapter_name]
    except KeyError as exc:
        raise ValueError(f"Unknown adapter: {adapter_name}") from exc
    return factory(config)
