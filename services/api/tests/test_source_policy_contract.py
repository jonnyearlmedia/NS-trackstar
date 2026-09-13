from __future__ import annotations

import json
from pathlib import Path

from ns_trackstar_api.source_policy import SOURCE_FRESHNESS_POLICIES


def test_every_production_source_has_a_freshness_policy_and_safe_cadence() -> None:
    configs = []
    for path in sorted(Path("config/sources").glob("*.json")):
        payload = json.loads(path.read_text())
        configs.append((path, payload))

    assert len(configs) == 23
    config_keys = {str(payload["key"]) for _, payload in configs}
    assert config_keys == set(SOURCE_FRESHNESS_POLICIES)

    for path, payload in configs:
        key = str(payload["key"])
        interval = int(payload["poll_minutes"])
        policy = SOURCE_FRESHNESS_POLICIES[key]
        assert policy.recommended_min_minutes <= interval <= policy.recommended_max_minutes, (
            f"{path.name}: poll_minutes={interval} is outside "
            f"{policy.recommended_min_minutes}-{policy.recommended_max_minutes}"
        )


def test_fast_sources_are_intentional_and_static_sources_stay_slow() -> None:
    assert SOURCE_FRESHNESS_POLICIES["napa-city.legistar"].recommended_min_minutes == 60
    assert SOURCE_FRESHNESS_POLICIES["solano-county.legistar"].recommended_min_minutes == 60
    assert SOURCE_FRESHNESS_POLICIES["vallejo.civicclerk"].recommended_max_minutes == 120
    assert SOURCE_FRESHNESS_POLICIES["federal-register.napa-solano"].recommended_min_minutes == 1440
    assert SOURCE_FRESHNESS_POLICIES["napa-county.parcels"].recommended_max_minutes == 10080
    assert SOURCE_FRESHNESS_POLICIES["solano-county.parcels"].recommended_max_minutes == 10080
