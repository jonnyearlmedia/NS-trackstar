from ns_trackstar_api.product_app import app


def test_product_routes_are_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/briefing" in paths
    assert "/projects/{project_id}/context" in paths
    assert "/map/projects" in paths
    assert "/search/projects" in paths
