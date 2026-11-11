from datetime import date
from decimal import Decimal
from sqlalchemy import String, Text, Numeric, Date, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class FilmPO(Base):
    __tablename__ = 'film_purchase_orders'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_date: Mapped[date | None] = mapped_column(Date)
    supplier_id: Mapped[str] = mapped_column(String(500), default='')
    staff_id: Mapped[str] = mapped_column(String(500), default='')
    note: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(500), default='')
    source: Mapped[dict] = mapped_column(JSON, default=dict)


class FilmLine(Base):
    __tablename__ = 'film_order_lines'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    po_id: Mapped[str] = mapped_column(String(100), default='', index=True)
    material_id: Mapped[str] = mapped_column(String(100), default='', index=True)
    resin: Mapped[str] = mapped_column(String(500), default='')
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    note: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(500), default='')
    delivery_date: Mapped[date | None] = mapped_column(Date)
    order_date: Mapped[date | None] = mapped_column(Date)
    supplier_id: Mapped[str] = mapped_column(String(500), default='')
    source: Mapped[dict] = mapped_column(JSON, default=dict)
