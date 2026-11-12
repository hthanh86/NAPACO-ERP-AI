from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.auth.models import LoginSession, User
from app.auth.access import safe_next


def test_all_pages_and_static_templates_require_login(clients):
    with TestClient(app) as guest:
        for path in ['/', '/?view=create', '/?view=list', '/?view=be', '/?view=film',
                     '/?view=film-stock', '/?view=film-create', '/?view=film-receive',
                     '/static/orders/create.html', '/static/shared/menu.html', '/unknown-page']:
            response = guest.get(path, follow_redirects=False)
            # Unknown routes are inaccessible too (404), never business content.
            if path == '/unknown-page':
                assert response.status_code == 404
                continue
            assert response.status_code == 303, (path, response.text)
            assert parse_qs(urlsplit(response.headers['location']).query)['next'] == [path]
        for path in ['/api/me', '/api/health', '/api/google-status', '/api/docs', '/openapi.json']:
            assert guest.get(path).status_code == 401, path
        for path in ['/login', '/static/auth/login.css', '/static/auth/login.js']:
            assert guest.get(path).status_code == 200, path
        assert guest.post('/api/legacy/searchUserDriveFiles', json={'args':['test'], 'request_id':'x'*32}).status_code == 401


def test_logout_revokes_session_and_expired_or_disabled_user_is_blocked(clients):
    client, reader, conn = clients
    cookie = client.cookies.get('napaco_session')
    assert client.get('/static/orders/create.html').status_code == 200
    assert client.get('/api/me').json()['google_connected'] is False
    assert client.post('/api/logout').status_code == 200
    client.cookies.set('napaco_session', cookie)
    assert client.get('/api/me').status_code == 401
    assert client.get('/?view=create', follow_redirects=False).status_code == 303
    conn.execute(LoginSession.__table__.update().where(LoginSession.user_id == '_TEST_READER').values(expires_at=datetime.utcnow()-timedelta(seconds=1)))
    assert reader.get('/api/me').status_code == 401
    conn.execute(LoginSession.__table__.update().where(LoginSession.user_id == '_TEST_READER').values(expires_at=datetime.utcnow()+timedelta(hours=1)))
    conn.execute(User.__table__.update().where(User.id == '_TEST_READER').values(active=False))
    assert reader.get('/api/me').status_code == 401


def test_next_rejects_external_redirects():
    for value in ['https://example.org', '//example.org', '/\\example.org', '/\nLocation: x', '/login']:
        assert safe_next(value) == '/'
    assert safe_next('/?view=film-stock') == '/?view=film-stock'


def test_employee_tool_validates_identity_and_revokes_sessions(clients):
    from argparse import Namespace
    import pytest
    from sqlalchemy.orm import Session as OrmSession
    from app.auth.manage_users import manage
    from app.auth.models import RolePermission
    client, _, connection = clients
    with OrmSession(bind=connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as db:
        db.add(RolePermission(role='_TEST_ROLE', permission='ORDER_CREATE', allowed=True)); db.commit()
        args = Namespace(action='add', id='_TEST_NEW', name='Nhân viên mới', email='NEW@example.test', role='_TEST_ROLE')
        result = manage(db, args)
        assert result['email'] == 'new@example.test' and result['active']
        with pytest.raises(ValueError):
            manage(db, Namespace(**{**vars(args), 'id':'_TEST_DUPLICATE'}))
        with pytest.raises(ValueError):
            manage(db, Namespace(**{**vars(args), 'id':'_TEST_BAD', 'role':'LOCAL_ADMIN'}))
        manage(db, Namespace(action='disable', id='_TEST_READER'))
        assert not db.get(User, '_TEST_READER').active
        assert not db.scalars(select(LoginSession).where(LoginSession.user_id == '_TEST_READER')).all()
