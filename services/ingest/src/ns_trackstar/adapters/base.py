from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ns_trackstar.models import CollectorResult


@dataclass(frozen=True, slots=True)
class SourceConfig:
    key: str
    name: str
    jurisdiction: str | None
    base_url: str
    poll_minutes: int
    options: dict[str, Any]


class CollectorAdapter(ABC):
    """Contract implemented by every NS Trackstar source adapter.

    Adapters normalize transport differences without flattening jurisdiction-specific
    fields. Raw payloads must be preserved by the calling ingestion pipeline.
    """

    def __init__(self, config: SourceConfig) -> None:
        self.config = config

    @abstractmethod
    async def collect(self) -> CollectorResult:
        """Fetch the source and return normalized records plus health fingerprints."""
        raise NotImplementedError

    async def canary(self) -> bool:
        """Run a cheap source-specific health assertion before accepting a zero-result run."""
        return True
