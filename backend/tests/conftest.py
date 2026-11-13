"""Integration tests against MySQL, isolated in a rollback-only outer transaction."""
from datetime import date
from decimal import Decimal
import secrets
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session as OrmSession
from app.main import app
from app.core.database import engine, get_db
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.auth.models import User
from app.modules.orders.models import Order, OrderLine
from app.auth.security import hash_password


@pytest.fixture
def qc_drive(monkeypatch):
    """QC integration tests exercise MySQL; Drive calls are explicitly mocked."""
    from app.modules.qc import drive_bundle
    from app.modules.qc.models import QualityCheck
    monkeypatch.setattr(drive_bundle, 'access_token', lambda db,user:'mock-token')
    monkeypatch.setattr(drive_bundle, 'in_scope', lambda db,token,identifier,writable=False:{'id':identifier})
    def prepare(db,user,identifier):
        obj=db.get(QualityCheck,identifier)
        obj.drive_folder_id='mock-folder-'+identifier
        obj.source={**(obj.source or {}),drive_bundle.JOB:{'pending':False,'error':''}}
        db.commit()
        return obj
    monkeypatch.setattr(drive_bundle, 'prepare', prepare)


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


