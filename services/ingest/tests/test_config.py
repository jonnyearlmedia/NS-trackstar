import json

from ns_trackstar.adapters.arcgis import ArcGISRestAdapter
from ns_trackstar.config import load_source_config
from ns_trackstar.registry import build_adapter


def test_config_builds_registered_adapter(tmp_path) -> None:
    path = tmp_path / "source.json"
    path.write_text(
        json.dumps(
            {
                "key": "test.parcels",
                "name": "Test Parcels",
                "jurisdiction": "Test County",
                "adapter": "arcgis_rest",
                "base_url": "https://example.test",
                "poll_minutes": 1440,
                "options": {"layer_url": "https://example.test/FeatureServer/0"},
            }
        )
    )

    adapter_name, config = load_source_config(path)
    adapter = build_adapter(adapter_name, config)

    assert adapter_name == "arcgis_rest"
    assert isinstance(adapter, ArcGISRestAdapter)
    assert config.key == "test.parcels"
