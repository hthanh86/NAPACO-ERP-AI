from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.auth.models import RolePermission, User, LoginSession
from app.core.models import Audit
from app.auth.security import check_password


def test_user_admin_boundaries_and_lifecycle(clients):
    admin, reader, conn = clients
    with TestClient(app) as guest:
        assert guest.get('/users', follow_redirects=False).status_code == 303
        assert guest.get('/api/admin/users').status_code == 401
    assert reader.get('/users').status_code == 403
    assert reader.get('/static/auth/users.html').status_code == 403
    assert reader.get('/api/admin/users').status_code == 403
    assert reader.put('/api/admin/users/_TEST_ADMIN/password', json={'password':'test password 123'}).status_code == 403
    conn.execute(RolePermission.__table__.insert().values(role='_TEST_STAFF', permission='ORDER_CREATE', allowed=True))
    assert admin.get('/users').status_code == 200
    payload = dict(id='_TEST_WEB', name='Nhân viên web', email='WEB@example.test', role='_TEST_STAFF')
    assert admin.post('/api/admin/users', json=payload).status_code == 200
    assert admin.post('/api/admin/users', json={**payload, 'id':'_TEST_DUP'}).status_code == 422
    assert admin.put('/api/admin/users/_TEST_ADMIN', json={**payload, 'id':'_TEST_ADMIN'}).status_code == 403
    assert admin.post('/api/admin/users', json={**payload, 'id':'_TEST_BAD', 'role':'LOCAL_ADMIN'}).status_code == 422
    assert admin.put('/api/admin/users/_TEST_WEB/password', json={'password':'short'}).status_code == 422
    password = 'new secure password 123'
    assert admin.put('/api/admin/users/_TEST_WEB/password', json={'password':password}).status_code == 200
    encoded = conn.execute(select(User.password_hash).where(User.id == '_TEST_WEB')).scalar_one()
    assert check_password(password, encoded)
    with TestClient(app) as employee:
        assert employee.post('/api/login', json={'username':'_TEST_WEB', 'password':password}).status_code == 200
        assert admin.put('/api/admin/users/_TEST_WEB', json={**payload, 'name':'Tên mới'}).status_code == 200
        assert employee.get('/api/me').status_code == 401
        assert employee.post('/api/login', json={'username':'_TEST_WEB', 'password':password}).status_code == 200
        assert admin.put('/api/admin/users/_TEST_WEB/password', json={'password':password+'2'}).status_code == 200
        assert employee.get('/api/me').status_code == 401
    assert admin.post('/api/admin/users/_TEST_WEB/disable').status_code == 200
    assert admin.post('/api/admin/users/_TEST_WEB/enable').status_code == 200
    listing = admin.get('/api/admin/users').json()
    assert 'password_hash' not in str(listing) and password not in str(listing)
    details = conn.execute(select(Audit.details).where(Audit.entity_id == '_TEST_WEB')).scalars().all()
    assert details and password not in str(details)


def test_admin_delegates_management_and_revokes_sessions(clients):
    admin, reader, conn = clients
    conn.execute(RolePermission.__table__.insert().values(role='TEST_READER', permission='ORDER_CREATE', allowed=False))
    assert admin.put('/api/admin/roles/TEST_READER/management', json={'allowed':True}).status_code == 200
    assert reader.get('/api/me').status_code == 401
    assert conn.execute(select(RolePermission.allowed).where(RolePermission.role == 'TEST_READER', RolePermission.permission == 'USER_MANAGE')).scalar_one()
    # Use a new session for the delegated role, without needing its fixture password.
    from datetime import datetime, timedelta
    from app.auth.security import token_hash
    token = 'delegated-session-test'
    conn.execute(LoginSession.__table__.insert().values(token_hash=token_hash(token), user_id='_TEST_READER', expires_at=datetime.utcnow()+timedelta(hours=1)))
    reader.cookies.set('napaco_session', token)
    assert reader.get('/api/admin/users').status_code == 200
    assert reader.put('/api/admin/roles/TEST_READER/management', json={'allowed':False}).status_code == 403
    assert reader.post('/api/admin/users/_TEST_READER/disable').status_code == 403
    assert admin.put('/api/admin/roles/TEST_READER/management', json={'allowed':False}).status_code == 200
    assert reader.get('/api/admin/users').status_code == 401
