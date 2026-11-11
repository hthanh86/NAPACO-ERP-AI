import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import select, delete
from app.core.database import get_db
from app.core.paths import FRONTEND_ROOT
from app.auth.models import User, LoginSession
from app.auth.security import check_password, token_hash, current_user, profile
from app.auth.schemas import Login

router = APIRouter()
attempts = defaultdict(deque)

@router.get('/login')
def login_page():
    return FileResponse(FRONTEND_ROOT / 'auth/login.html')


@router.post('/api/login')
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


@router.post('/api/logout')
def logout(request: Request, response: Response, db=Depends(get_db)):
    token = request.cookies.get('napaco_session', '')
    if token:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(token)))
        db.commit()
    response.delete_cookie('napaco_session')
    return {'ok': True}


@router.get('/api/me')
def me(user=Depends(current_user), db=Depends(get_db)):
    return profile(db, user)
