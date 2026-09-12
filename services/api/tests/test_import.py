from ns_trackstar_api.app import app


def test_app_metadata() -> None:
    assert app.title == "NS Trackstar API"
    assert app.version == "0.1.0"
