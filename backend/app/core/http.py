import logging
import time
from contextlib import nullcontext
from app.core.performance import trace, record, trace_id
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError, IntegrityError


def configure_http(app):
    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        host = request.headers.get('host', '')
        if host not in {'127.0.0.1:8000', 'localhost:8000', 'testserver'}:
            return JSONResponse({'detail': 'Ứng dụng thử nghiệm chỉ phục vụ localhost.'}, status_code=403)
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            origin = request.headers.get('origin')
            if origin and origin not in {'http://127.0.0.1:8000', 'http://localhost:8000', 'http://testserver'}:
                return JSONResponse({'detail': 'Nguồn yêu cầu không hợp lệ.'}, status_code=403)
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail': 'Nguồn yêu cầu không hợp lệ.'}, status_code=403)
            if request.headers.get('content-length', '').isdigit() and int(request.headers['content-length']) > 23_000_000:
                return JSONResponse({'detail': 'Yêu cầu quá lớn.'}, status_code=413)
        start = time.perf_counter()
        with trace('qc.request') if request.url.path.startswith('/api/qc') else nullcontext():
            response = await call_next(request)
            if request.url.path.startswith('/api/qc'):
                endpoint = request.scope.get('endpoint')
                record('qc.endpoint.' + getattr(endpoint, '__name__', 'unknown'), time.perf_counter() - start,
                       ok=response.status_code < 400, status=response.status_code)
                response.headers['X-QC-Trace'] = trace_id()
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Server-Timing'] = f'app;dur={(time.perf_counter()-start)*1000:.1f}'
        return response


    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        # Do not log exception parameters: they can contain confidential records.
        logging.error('Database operation failed: %s', type(exc).__name__)
        return JSONResponse({'detail': 'Không truy cập được dữ liệu. Vui lòng thử lại; giao dịch ghi bị lỗi sẽ được hủy.'},
                            status_code=409 if isinstance(exc, IntegrityError) else 503)
