from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.auth.models import RolePermission, LoginSession
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.core.models import Audit


def test_catalog_pages_and_paginated_read(clients):
    admin, reader, connection = clients
    with TestClient(app) as guest:
        assert guest.get('/master/customers', follow_redirects=False).status_code == 303
        assert guest.get('/api/master/customers').status_code == 401
    for kind in ['customers', 'products', 'suppliers']:
        page = reader.get('/master/' + kind)
        assert page.status_code == 200
        assert '/static/shared/navigation.js' in page.text
        result = reader.get('/api/master/' + kind, params={'size': 1}).json()
        assert len(result['items']) <= 1 and not result['can_manage']
    result = reader.get('/api/master/products', params={'customer_id': '_TEST_C1', 'q': '_TEST_P'}).json()
    assert [item['id'] for item in result['items']] == ['_TEST_P1']
    assert admin.get('/api/master/customers?size=1000').status_code == 422
    assert admin.get('/users').status_code == 200
    assert '/static/shared/navigation.js' in admin.get('/users').text


def test_catalog_write_permissions_validation_and_conflict(clients):
    admin, reader, connection = clients
    assert reader.post('/api/master/customers', json={'name': 'Không được ghi'}).status_code == 403
    before = connection.scalar(select(func.count()).select_from(Customer))
    assert admin.post('/api/master/customers', json={'name': '  '}).status_code == 422
    assert connection.scalar(select(func.count()).select_from(Customer)) == before
    response = admin.post('/api/master/customers', json={'name': 'Khách Master', 'phone':'0123456'})
    assert response.status_code == 201, response.text
    customer = response.json()
    assert customer['id'].startswith('KH') and len(customer['version']) == 64
    updated = admin.put('/api/master/customers/'+customer['id'], json={'name':'Tên mới','version':customer['version']})
    assert updated.status_code == 200
    assert admin.put('/api/master/customers/'+customer['id'], json={'name':'Ghi đè','version':customer['version']}).status_code == 409
    product = {'name':'Sản phẩm master','customer_id':customer['id'],'code':'MST','type':'1','unit':'Cái','price':'123.4500'}
    assert admin.post('/api/master/products', json={**product,'customer_id':'_MISSING'}).status_code == 422
    assert admin.post('/api/master/products', json={**product,'price':'-1'}).status_code == 422
    response = admin.post('/api/master/products', json=product)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved['source_customer_id'] == customer['id']
    assert admin.put('/api/master/products/'+saved['id'], json={**product,'customer_id':'_TEST_C2','version':saved['version']}).status_code == 422
    assert connection.scalar(select(Product.customer_id).where(Product.id == saved['id'])) == customer['id']
    assert connection.scalar(select(func.count()).select_from(Audit).where(Audit.entity_id == saved['id'])) == 1
    # Delegated catalog permission is honored by the same backend boundary.
    connection.execute(RolePermission.__table__.insert().values(role='TEST_READER',permission='CUSTOMER_MANAGE',allowed=True))
    assert reader.post('/api/master/customers', json={'name':'Khách được ủy quyền'}).status_code == 201


def test_permission_matrix_atomicity_and_session_revocation(clients):
    admin, reader, connection = clients
    connection.execute(RolePermission.__table__.insert().values(role='TEST_READER',permission='ORDER_EDIT',allowed=False))
    metadata = admin.get('/api/admin/users?size=1').json()
    assert len(metadata['users']) == 1 and metadata['total'] >= 2
    assert 'CUSTOMER_MANAGE' in {p['code'] for p in metadata['permissions']}
    change = {'role':'TEST_READER','permission':'ORDER_EDIT','allowed':True,'expected':False}
    assert reader.put('/api/admin/permissions', json={'changes':[change]}).status_code == 403
    # Invalid second entry must leave the valid first entry unchanged.
    response = admin.put('/api/admin/permissions', json={'changes':[change,{**change,'permission':'UNKNOWN'}]})
    assert response.status_code == 422
    assert connection.scalar(select(RolePermission.allowed).where(RolePermission.role=='TEST_READER',RolePermission.permission=='ORDER_EDIT')) is False
    assert admin.put('/api/admin/permissions', json={'changes':[{**change,'role':'LOCAL_ADMIN'}]}).status_code == 422
    assert admin.put('/api/admin/permissions', json={'changes':[change]}).status_code == 200
    assert connection.scalar(select(RolePermission.allowed).where(RolePermission.role=='TEST_READER',RolePermission.permission=='ORDER_EDIT')) is True
    from sqlalchemy.orm import Session
    from app.auth.legacy_adapter import permission_rows
    with Session(bind=connection, join_transaction_mode='create_savepoint') as db:
        rows = permission_rows(db)
        role_column = rows[0].index('TEST_READER')
        assert next(row for row in rows[1:] if row[0] == 'ORDER_EDIT')[role_column] == '1'
    assert not connection.scalar(select(LoginSession.token_hash).where(LoginSession.user_id=='_TEST_READER'))
    assert reader.get('/api/me').status_code == 401
    assert admin.put('/api/admin/permissions', json={'changes':[change]}).status_code == 409
    assert admin.put('/api/admin/permissions', json={'changes':[{**change,'permission':'SUPPLIER_MANAGE'}]}).status_code == 200


def test_matrix_controls_existing_business_permissions(clients):
    from datetime import datetime, timedelta
    from app.auth.models import User
    from app.auth.security import token_hash
    admin, reader, connection = clients
    connection.execute(User.__table__.update().where(User.id == '_TEST_READER').values(email='_test_reader@example.test'))
    connection.execute(RolePermission.__table__.insert().values(role='TEST_READER', permission='FILM_PO_VIEW', allowed=False))
    call = {'args':[{}], 'request_id':'matrix-legacy-permission-check'}
    denied = reader.post('/api/legacy/getFilmOrders', json=call)
    assert denied.status_code == 422 and 'FILM_PO_VIEW' in denied.text, denied.text
    change = {'role':'TEST_READER','permission':'FILM_PO_VIEW','allowed':True,'expected':False}
    assert admin.put('/api/admin/permissions', json={'changes':[change]}).status_code == 200
    token = 'test-relogin-after-matrix'
    connection.execute(LoginSession.__table__.insert().values(token_hash=token_hash(token), user_id='_TEST_READER', expires_at=datetime.utcnow()+timedelta(hours=1)))
    reader.cookies.set('napaco_session', token)
    allowed = reader.post('/api/legacy/getFilmOrders', json=call)
    assert allowed.status_code == 200, allowed.text
