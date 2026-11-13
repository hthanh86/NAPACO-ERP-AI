"""Application assembly only. Business code lives in its owning module."""
from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from app.core import model_registry
from app.core.http import configure_http
from app.core.paths import FRONTEND_ROOT
from app.auth.api import router as auth_router
from app.auth.admin import router as admin_router
from app.modules.master.api import router as master_router
from app.modules.orders.api import router as orders_router
from app.modules.products.api import router as products_router
from app.modules.qc.api import router as qc_router
from app.modules.qc.templates import router as qc_templates_router
from app.modules.qc.template_runtime import router as qc_template_runtime_router
from app.modules.qc.signing import router as qc_signing_router
from app.integrations.google.oauth import router as google_router
from app.compatibility.api import router as compatibility_router
from app.system.api import router as system_router
from app.auth.access import require_session
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

app = FastAPI(title='Napaco ERP Local', version='0.2.0', docs_url=None, redoc_url=None,
              dependencies=[Depends(require_session)], openapi_url=None)
for router in (orders_router, products_router, qc_templates_router, qc_template_runtime_router, qc_signing_router, qc_router, auth_router, admin_router, master_router, compatibility_router, google_router, system_router):
    app.include_router(router)
static = StaticFiles(directory=FRONTEND_ROOT)


@app.get('/api/docs', include_in_schema=False)
def docs():
    return get_swagger_ui_html(openapi_url='/openapi.json', title='Napaco ERP API')


@app.get('/openapi.json', include_in_schema=False)
def schema():
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


@app.api_route('/static/{path:path}', methods=['GET', 'HEAD'], include_in_schema=False)
async def static_file(path: str, request: Request):
    return await static.get_response(path, request.scope)

configure_http(app)
