from __future__ import annotations

import json
from pathlib import Path

from ns_trackstar.adapters.base import SourceConfig


def load_source_config(path: str | Path) -> tuple[str, SourceConfig]:
    source_path = Path(path)
    payload = json.loads(source_path.read_text())

    adapter = str(payload["adapter"])
    config = SourceConfig(
        key=str(payload["key"]),
        name=str(payload["name"]),
        jurisdiction=payload.get("jurisdiction"),
        base_url=str(payload["base_url"]),
        poll_minutes=int(payload["poll_minutes"]),
        options=dict(payload.get("options") or {}),
    )
    return adapter, config
