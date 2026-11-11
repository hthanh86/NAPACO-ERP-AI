import logging
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text, delete
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from .db import engine, get_db
from .models import User, LoginSession, ImportRun
from .auth import check_password, token_hash, current_user, profile
from .orders import router

app = FastAPI(title='Napaco ERP Local', version='0.1.0', docs_url='/api/docs', redoc_url=None)
app.include_router(router)
frontend = Path('/app/frontend')
app.mount('/static', StaticFiles(directory=frontend), name='static')
attempts = defaultdict(deque)


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
        if request.headers.get('content-length', '').isdigit() and int(request.headers['content-length']) > 2_000_000:
            return JSONResponse({'detail': 'Yêu cầu quá lớn.'}, status_code=413)
    start = time.perf_counter()
    response = await call_next(request)
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


@app.get('/')
def index():
    return FileResponse(frontend / 'index.html')


@app.get('/api/health')
def health():
    with engine.connect() as db:
        version = db.scalar(text('SELECT VERSION()'))
        revision = db.scalar(text('SELECT version_num FROM alembic_version'))
    return {'status': 'ok', 'database': 'MySQL ' + version, 'migration': revision, 'mode': 'local'}


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=500)


@app.post('/api/login')
def login(payload: Login, request: Request, response: Response, db=Depends(get_db)):
    key = request.client.host
    recent = attempts[key]
    now = time.monotonic()
    while recent and now - recent[0] > 300:
        recent.popleft()
    if len(recent) >= 10:
        raise HTTPException(429, 'Đã thử quá nhiều lần. Vui lòng chờ 5 phút.')
    recent.append(now)
    user = db.scalar(select(User).where((User.id == payload.username) | (User.email == payload.username)))
    if not user or not user.active or not check_password(payload.password, user.password_hash):
        raise HTTPException(401, 'Tài khoản hoặc mật khẩu không đúng.')
    recent.clear()
    db.execute(delete(LoginSession).where(LoginSession.expires_at < datetime.utcnow()))
    token = secrets.token_urlsafe(40)
    db.add(LoginSession(token_hash=token_hash(token), user_id=user.id,
                        expires_at=datetime.utcnow() + timedelta(hours=8)))
    db.commit()
    # HTTP localhost only. Production deployment must use HTTPS and Secure cookies.
    response.set_cookie('napaco_session', token, httponly=True, samesite='strict', max_age=8 * 3600)
    return profile(db, user)


@app.post('/api/logout')
def logout(request: Request, response: Response, db=Depends(get_db)):
    token = request.cookies.get('napaco_session', '')
    if token:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(token)))
        db.commit()
    response.delete_cookie('napaco_session')
    return {'ok': True}


@app.get('/api/me')
def me(user=Depends(current_user), db=Depends(get_db)):
    return profile(db, user)


@app.get('/api/migration-status')
def migration_status(user=Depends(current_user), db=Depends(get_db)):
    run = db.scalar(select(ImportRun).order_by(ImportRun.created_at.desc()))
    return {'imported': bool(run), 'counts': run.report['counts'] if run else {},
            'quality': run.report.get('quality', {}) if run else {},
            'reconciliation': run.report.get('reconciliation') if run else None}
