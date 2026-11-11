import hashlib
import hmac
import secrets
from datetime import datetime
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from app.core.database import get_db
from app.auth.models import User, LoginSession, RolePermission


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000).hex()
    return 'pbkdf2$600000$' + salt + '$' + digest


def check_password(password, encoded):
    try:
        _, rounds, salt, expected = encoded.split('$')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, AttributeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, db=Depends(get_db)):
    token = request.cookies.get('napaco_session', '')
    session = db.get(LoginSession, token_hash(token)) if token else None
    user = db.get(User, session.user_id) if session and session.expires_at > datetime.utcnow() else None
    if not user or not user.active:
        raise HTTPException(401, 'Vui lòng đăng nhập.')
    return user


def require(db, user, permission):
    if user.role == 'LOCAL_ADMIN':
        return
    grant = db.get(RolePermission, (user.role, permission))
    if not grant or not grant.allowed:
        raise HTTPException(403, 'Bạn chưa có quyền ' + permission + '.')


def profile(db, user):
    permissions = ['ORDER_CREATE', 'ORDER_EDIT'] if user.role == 'LOCAL_ADMIN' else list(
        db.scalars(select(RolePermission.permission).where(RolePermission.role == user.role,
                                                        RolePermission.allowed.is_(True))))
    return {'id': user.id, 'name': user.name, 'role': user.role, 'permissions': permissions}
