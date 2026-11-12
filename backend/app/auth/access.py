"""Authentication boundary shared by pages, APIs and static files."""
from urllib.parse import quote, urlsplit
from fastapi import Depends, HTTPException, Request
from app.auth.security import current_user, require
from app.core.database import get_db


def safe_next(value):
    value = str(value or '/')
    if not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c) < 32 for c in value):
        return '/'
    if urlsplit(value).path in {'/login', '/auth/google/start', '/auth/google/callback'}:
        return '/'
    return value


def require_session(request: Request, db=Depends(get_db)):
    public = {'/login', '/api/login', '/auth/google/start', '/auth/google/callback',
              '/static/auth/login.css', '/static/auth/login.js'}
    if request.url.path in public:
        return
    try:
        user = current_user(request, db)
        if request.url.path == '/static/auth/users.html':
            require(db, user, 'USER_MANAGE')
    except HTTPException as error:
        if error.status_code != 401:
            raise
        if request.url.path.startswith('/api/') or request.url.path == '/openapi.json':
            raise
        target = safe_next(request.url.path + ('?' + request.url.query if request.url.query else ''))
        raise HTTPException(303, headers={'Location': '/login?next=' + quote(target, safe='')})
