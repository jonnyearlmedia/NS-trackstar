from __future__ import annotations

from ns_trackstar_api.app import app
from ns_trackstar_api.product import router as product_router

app.include_router(product_router)
