from __future__ import annotations

from ns_trackstar_api.app import app
from ns_trackstar_api.area import router as area_router
from ns_trackstar_api.cadence import router as cadence_router
from ns_trackstar_api.categories import router as categories_router
from ns_trackstar_api.churn import router as churn_router
from ns_trackstar_api.freshness import router as freshness_router
from ns_trackstar_api.lifecycle_audit import router as lifecycle_audit_router
from ns_trackstar_api.product import router as product_router
from ns_trackstar_api.public_changes import router as public_changes_router
from ns_trackstar_api.quality import router as quality_router
from ns_trackstar_api.search import router as search_router
from ns_trackstar_api.taxonomy import router as taxonomy_router

app.include_router(product_router)
app.include_router(area_router)
app.include_router(public_changes_router)
app.include_router(taxonomy_router)
app.include_router(cadence_router)
app.include_router(lifecycle_audit_router)
app.include_router(freshness_router)
app.include_router(categories_router)
app.include_router(churn_router)
app.include_router(quality_router)
app.include_router(search_router)
