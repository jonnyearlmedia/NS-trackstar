"""Contract: a zero-record run must never be able to masquerade as a healthy one.

Trackstar's failure mode is silence. A collector that quietly returns nothing keeps
the map looking fine while the jurisdiction goes stale, so every adapter has to be able
to tell "nothing happened today" apart from "the source stopped answering me".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ns_trackstar.adapters.base import CollectorAdapter
from ns_trackstar.config import load_source_config
from ns_trackstar.health import RunSignal, classify_health
from ns_trackstar.models import SourceHealthState
from ns_trackstar.registry import ADAPTERS, build_adapter

PRODUCTION_CONFIGS = sorted(Path("config/sources").glob("*.json"))
SMOKE_CONFIGS = sorted(Path("config/smoke").glob("*.json"))

# Adapters whose canary needs a live tenant or document set to be meaningful still have
# to declare one; this maps each adapter family to the config option that carries it.
CANARY_OPTION_BY_ADAPTER: dict[str, tuple[str, ...]] = {
    "arcgis_rest": ("canary_fields", "min_expected_records", "expected_geometry_type"),
    "etrakit": ("canary_kinds",),
    "abc_ca": ("report_types",),
}


def test_every_registered_adapter_defines_its_own_canary():
    """Inheriting the default `return True` would make every empty run look healthy."""

    inherited = []
    for name, factory in ADAPTERS.items():
        target = factory if isinstance(factory, type) else type(factory)
        if target.canary is CollectorAdapter.canary:
            inherited.append(name)
    assert inherited == [], f"adapters relying on the default canary: {inherited}"


@pytest.mark.parametrize("path", PRODUCTION_CONFIGS, ids=lambda path: path.stem)
def test_production_configs_load_and_build_an_adapter(path: Path):
    adapter_name, config = load_source_config(path)
    assert adapter_name in ADAPTERS, f"{path.name} names an unregistered adapter"
    adapter = build_adapter(adapter_name, config)
    assert isinstance(adapter, CollectorAdapter)
    assert config.poll_minutes > 0


@pytest.mark.parametrize("path", SMOKE_CONFIGS, ids=lambda path: path.stem)
def test_smoke_configs_load_and_build_an_adapter(path: Path):
    adapter_name, config = load_source_config(path)
    assert adapter_name in ADAPTERS, f"{path.name} names an unregistered adapter"
    assert isinstance(build_adapter(adapter_name, config), CollectorAdapter)


@pytest.mark.parametrize("path", PRODUCTION_CONFIGS, ids=lambda path: path.stem)
def test_production_configs_declare_what_their_canary_checks(path: Path):
    adapter_name, config = load_source_config(path)
    required = CANARY_OPTION_BY_ADAPTER.get(adapter_name)
    if required is None:
        return
    present = [option for option in required if config.options.get(option)]
    assert present, (
        f"{path.name} uses {adapter_name} but declares none of {required}, "
        "so its canary cannot tell an empty day from a broken source"
    )


@pytest.mark.parametrize("path", SMOKE_CONFIGS, ids=lambda path: path.stem)
def test_smoke_configs_are_keyed_as_smoke(path: Path):
    """A smoke key can never be mistaken for a promoted production source."""

    payload = json.loads(path.read_text())
    key = str(payload["key"])
    production_keys = {
        json.loads(candidate.read_text())["key"] for candidate in PRODUCTION_CONFIGS
    }
    assert key not in production_keys, f"{path.name} collides with a production source key"


def signal(**overrides) -> RunSignal:
    base = {
        "success": True,
        "parse_ok": True,
        "canary_ok": True,
        "consecutive_failures": 0,
        "last_success_at": datetime.now(UTC),
        "expected_poll_minutes": 120,
    }
    return RunSignal(**{**base, **overrides})


def test_a_clean_empty_run_is_only_healthy_when_every_check_passed():
    assert classify_health(signal()) is SourceHealthState.HEALTHY
    # Each of these alone is enough to stop calling an empty run a good one.
    assert classify_health(signal(canary_ok=False)) is SourceHealthState.DEGRADED
    assert classify_health(signal(parse_ok=False)) is SourceHealthState.DEGRADED
    assert classify_health(signal(success=False)) is SourceHealthState.BROKEN
    assert classify_health(signal(schema_changed=True)) is SourceHealthState.SCHEMA_CHANGED
    assert classify_health(signal(blocked=True)) is SourceHealthState.BLOCKED


def test_blocked_outranks_every_other_signal():
    """An access restriction is the real answer, not a schema or parse problem."""

    assert (
        classify_health(signal(blocked=True, schema_changed=True, success=False))
        is SourceHealthState.BLOCKED
    )


def test_a_source_that_stopped_being_polled_goes_delayed_not_healthy():
    stale = datetime.now(UTC) - timedelta(minutes=500)
    assert classify_health(signal(last_success_at=stale)) is SourceHealthState.DELAYED
    assert classify_health(signal(last_success_at=None)) is SourceHealthState.DELAYED


def test_repeated_failures_escalate_to_broken():
    assert classify_health(signal(consecutive_failures=2)) is SourceHealthState.HEALTHY
    assert classify_health(signal(consecutive_failures=3)) is SourceHealthState.BROKEN
