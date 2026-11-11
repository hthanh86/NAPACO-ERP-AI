"""Integration tests against MySQL, isolated in a rollback-only outer transaction."""
from datetime import date
from decimal import Decimal
import secrets
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session as OrmSession
from app.main import app
from app.db import engine, get_db
from app.models import Customer, Product, User, Order, OrderLine
from app.auth import hash_password


@pytest.fixture
def clients():
    connection = engine.connect()
    outer = connection.begin()
    password = secrets.token_urlsafe(18)
    with OrmSession(bind=connection, join_transaction_mode='create_savepoint') as db:
        db.add_all([Customer(id='_TEST_C1', name='Khách kiểm thử'), Customer(id='_TEST_C2', name='Khách khác')]);db.flush()
        db.add_all([Product(id='_TEST_P1', customer_id='_TEST_C1', name='Sản phẩm thử', unit='Cái', price=10),
                    Product(id='_TEST_P2', customer_id='_TEST_C2', name='Sản phẩm khách khác', unit='Cái', price=10),
                    User(id='_TEST_ADMIN', name='Kiểm thử', role='LOCAL_ADMIN', password_hash=hash_password(password), active=True),
                    User(id='_TEST_READER', name='Chỉ xem', role='TEST_READER', password_hash=hash_password(password), active=True)])
        db.commit()

    def override():
        with OrmSession(bind=connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as db:
            yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as admin, TestClient(app) as reader:
        assert admin.post('/api/login', json={'username':'_TEST_ADMIN','password':password}).status_code == 200
        assert reader.post('/api/login', json={'username':'_TEST_READER','password':password}).status_code == 200
        yield admin, reader, connection
    app.dependency_overrides.clear()
    outer.rollback();connection.close()


def payload():
    return {'customer_id':'_TEST_C1','po_number':'PO-KIEM-THU','order_date':'2026-11-11','lines':[
        {'product_id':'_TEST_P1','quantity':'12.5000','price':'1234.5678','unit':'Cái',
         'delivery_date':'2026-11-21','note':'Tiếng Việt','status':'Chờ sản xuất'}]}


def test_authentication_and_permissions(clients):
    admin, reader, _ = clients
    assert reader.post('/api/orders',json=payload(),headers={'Idempotency-Key':secrets.token_hex(16)}).status_code == 403
    assert admin.get('/api/me').json()['role'] == 'LOCAL_ADMIN'
    assert admin.post('/api/logout').status_code == 200
    assert admin.get('/api/orders').status_code == 401


def test_idempotency_and_decimal_accuracy(clients):
    admin, _, conn = clients
    key=secrets.token_hex(16)
    a=admin.post('/api/orders',json=payload(),headers={'Idempotency-Key':key})
    assert a.status_code == 201, a.text
    b=admin.post('/api/orders',json=payload(),headers={'Idempotency-Key':key})
    assert b.json()['id'] == a.json()['id']
    line=a.json()['lines'][0]
    assert Decimal(line['quantity']) == Decimal('12.5')
    assert Decimal(line['price']) == Decimal('1234.5678')
    changed=payload();changed['po_number']='OTHER'
    assert admin.post('/api/orders',json=changed,headers={'Idempotency-Key':key}).status_code == 409


def test_list_search_pagination_and_product_filter(clients):
    admin, _, _ = clients
    made = admin.post('/api/orders', json=payload(), headers={'Idempotency-Key':secrets.token_hex(16)}).json()
    result = admin.get('/api/orders', params={'q':'PO-KIEM-THU','customer_id':'_TEST_C1','status':'ACTIVE_ALL','size':1})
    assert result.status_code == 200, result.text
    assert result.json()['total'] == 1
    assert result.json()['items'][0]['id'] == made['id']
    assert admin.get('/api/orders?page=1&size=25').status_code == 200


def test_failed_second_line_rolls_back_header_and_first_line(clients):
    admin, _, conn=clients
    before=conn.scalar(select(func.count()).select_from(Order))
    before_lines=conn.scalar(select(func.count()).select_from(OrderLine))
    bad=payload();bad['lines'].append({**bad['lines'][0], 'product_id':'_TEST_P2'})
    result=admin.post('/api/orders',json=bad,headers={'Idempotency-Key':secrets.token_hex(16)})
    assert result.status_code == 422
    assert conn.scalar(select(func.count()).select_from(Order)) == before
    assert conn.scalar(select(func.count()).select_from(OrderLine)) == before_lines


def test_stale_update_is_rejected_and_original_progress_preserved(clients):
    admin, _, conn=clients
    created=admin.post('/api/orders',json=payload(),headers={'Idempotency-Key':secrets.token_hex(16)}).json()
    update=payload();update['version']=created['version'];update['lines'][0]['id']=created['lines'][0]['id']
    update['lines'][0]['quantity']='20'
    first=admin.put('/api/orders/'+created['id'],json=update)
    assert first.status_code == 200, first.text
    assert first.json()['version'] == 2
    assert Decimal(first.json()['lines'][0]['produced']) == 0
    assert admin.put('/api/orders/'+created['id'],json=update).status_code == 409
    assert Decimal(admin.get('/api/orders/'+created['id']).json()['lines'][0]['quantity']) == 20


def test_validation_and_cross_site_rejection(clients):
    admin, _, _=clients
    bad=payload();bad['lines'][0]['delivery_date']='2026-11-01'
    assert admin.post('/api/orders',json=bad,headers={'Idempotency-Key':secrets.token_hex(16)}).status_code == 422
    assert admin.post('/api/orders',json=payload(),headers={'Idempotency-Key':secrets.token_hex(16),'Origin':'https://untrusted.example'}).status_code == 403
    assert admin.get('/api/orders?page=0').status_code == 422
