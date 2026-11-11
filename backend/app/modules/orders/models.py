from datetime import datetime
from sqlalchemy import String, Text, Numeric, Integer, Date, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


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


class RequestKey(Base):
    __tablename__ = 'request_keys'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(String(100))
