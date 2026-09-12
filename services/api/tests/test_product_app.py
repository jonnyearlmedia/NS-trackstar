from ns_trackstar_api.app import app
from ns_trackstar_api.product import router as product_router


def test_product_routes_are_registered() -> None:
    core_paths = {getattr(route, "path", None) for route in app.routes}
    product_paths = {getattr(route, "path", None) for route in product_router.routes}

    assert "/briefing" in product_paths
    assert "/projects/{project_id}/context" in product_paths
    assert "/map/projects" in core_paths
    assert "/search/projects" in core_paths
