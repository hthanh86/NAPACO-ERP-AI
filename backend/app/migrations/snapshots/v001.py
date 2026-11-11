# Frozen schema for migration 001. Do not edit.
from datetime import datetime
from sqlalchemy import String, Text, Numeric, Integer, Date, DateTime, Boolean, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = 'customers'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    address: Mapped[str] = mapped_column(Text, default='')
    contact: Mapped[str] = mapped_column(String(500), default='')
    phone: Mapped[str] = mapped_column(String(200), default='')
    source: Mapped[dict] = mapped_column(JSON, default=dict)


class Product(Base):
    __tablename__ = 'products'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey('customers.id'), index=True)
    source_customer_id: Mapped[str] = mapped_column(String(100), default='')
    name: Mapped[str] = mapped_column(String(500), index=True)
    code: Mapped[str] = mapped_column(String(200), default='')
    type: Mapped[str] = mapped_column(String(50), default='')
    unit: Mapped[str] = mapped_column(String(100), default='Cái')
    price: Mapped[float] = mapped_column(Numeric(20, 4), default=0)
    source: Mapped[dict] = mapped_column(JSON, default=dict)


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    role: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    source: Mapped[dict] = mapped_column(JSON, default=dict)


class RolePermission(Base):
    __tablename__ = 'role_permissions'
    role: Mapped[str] = mapped_column(String(100), primary_key=True)
    permission: Mapped[str] = mapped_column(String(100), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginSession(Base):
    __tablename__ = 'login_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Order(Base):
    __tablename__ = 'orders'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey('customers.id'), index=True)
    order_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    delivery_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    po_number: Mapped[str] = mapped_column(String(300), default='', index=True)
    file_url: Mapped[str] = mapped_column(Text, default='')
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[dict] = mapped_column(JSON, default=dict)


class OrderLine(Base):
    __tablename__ = 'order_lines'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('orders.id'), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey('products.id'), index=True)
    source_product_id: Mapped[str] = mapped_column(String(100), default='')
    quantity: Mapped[float] = mapped_column(Numeric(20, 4))
    price: Mapped[float] = mapped_column(Numeric(20, 4), default=0)
    produced: Mapped[float] = mapped_column(Numeric(20, 4), default=0)
    delivered: Mapped[float] = mapped_column(Numeric(20, 4), default=0)
    remaining_source: Mapped[float | None] = mapped_column(Numeric(20, 4))
    note: Mapped[str] = mapped_column(Text, default='')
    delivery_date: Mapped[datetime | None] = mapped_column(Date)
    staff_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(100), default='Chờ sản xuất', index=True)
    unit: Mapped[str] = mapped_column(String(100), default='Cái')
    zone: Mapped[str] = mapped_column(String(100), default='CHO_SAN_XUAT')
    priority: Mapped[int] = mapped_column(Integer, default=0)
    film_line_id: Mapped[str] = mapped_column(String(100), default='')
    source: Mapped[dict] = mapped_column(JSON, default=dict)


class Sequence(Base):
    __tablename__ = 'sequences'
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[int] = mapped_column(Integer)


class Audit(Base):
    __tablename__ = 'audit_log'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    details: Mapped[dict] = mapped_column(JSON)


class RequestKey(Base):
    __tablename__ = 'request_keys'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(String(100))


class ImportRun(Base):
    __tablename__ = 'import_runs'
    checksum: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    report: Mapped[dict] = mapped_column(JSON)


class SourceRow(Base):
    __tablename__ = 'source_rows'
    __table_args__ = (UniqueConstraint('book', 'sheet', 'row_number'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book: Mapped[str] = mapped_column(String(30))
    sheet: Mapped[str] = mapped_column(String(200))
    row_number: Mapped[int] = mapped_column(Integer)
    cells: Mapped[list] = mapped_column(JSON)

metadata = Base.metadata
