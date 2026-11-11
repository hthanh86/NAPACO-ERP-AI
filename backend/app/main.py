"""Application assembly only. Business code lives in its owning module."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.core import model_registry
from app.core.http import configure_http
from app.core.paths import FRONTEND_ROOT
from app.auth.api import router as auth_router
from app.modules.orders.api import router as orders_router
from app.modules.products.api import router as products_router
from app.integrations.google.oauth import router as google_router
from app.compatibility.api import router as compatibility_router
from app.system.api import router as system_router

app = FastAPI(title='Napaco ERP Local', version='0.2.0', docs_url='/api/docs', redoc_url=None)
for router in (orders_router, products_router, auth_router, compatibility_router, google_router, system_router):
    app.include_router(router)
app.mount('/static', StaticFiles(directory=FRONTEND_ROOT), name='static')
configure_http(app)
