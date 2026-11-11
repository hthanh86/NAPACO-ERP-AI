# Frozen schema for migration 002.
from datetime import date
from decimal import Decimal
from sqlalchemy import String, Text, Numeric, Integer, Date, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class FilmSupplier(Base):
    __tablename__ = 'film_suppliers'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), default='')
    category: Mapped[str] = mapped_column(String(500), default='')
    source: Mapped[dict] = mapped_column(JSON, default=dict)


class FilmMaterial(Base):
    __tablename__ = 'film_materials'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    grade: Mapped[str] = mapped_column(String(500), default='')
    color: Mapped[str] = mapped_column(String(500), default='')
    esd: Mapped[str] = mapped_column(String(500), default='')
    thickness: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    width: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    source: Mapped[dict] = mapped_column(JSON, default=dict)


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


class FilmReceipt(Base):
    __tablename__ = 'film_receipts'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    receipt_date: Mapped[date | None] = mapped_column(Date)
    production_date: Mapped[date | None] = mapped_column(Date)
    line_id: Mapped[str] = mapped_column(String(100), default='', index=True)
    rolls: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    location: Mapped[str] = mapped_column(String(500), default='')
    status: Mapped[str] = mapped_column(String(500), default='')
    staff_id: Mapped[str] = mapped_column(String(500), default='')
    iqc_id: Mapped[str] = mapped_column(String(500), default='')
    note: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[dict] = mapped_column(JSON, default=dict)


class FilmMovement(Base):
    __tablename__ = 'film_movements'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    moved_at: Mapped[str] = mapped_column(String(500), default='')
    kind: Mapped[str] = mapped_column(String(500), default='')
    production_order_id: Mapped[str] = mapped_column(String(100), default='', index=True)
    receipt_id: Mapped[str] = mapped_column(String(100), default='', index=True)
    qc_id: Mapped[str] = mapped_column(String(500), default='')
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    issuer_id: Mapped[str] = mapped_column(String(500), default='')
    receiver_id: Mapped[str] = mapped_column(String(500), default='')
    note: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[dict] = mapped_column(JSON, default=dict)


class LegacyState(Base):
    __tablename__ = 'legacy_state'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_entries: Mapped[dict] = mapped_column(JSON, default=dict)
    cell_notes: Mapped[dict] = mapped_column(JSON, default=dict)


class LegacyRequest(Base):
    __tablename__ = 'legacy_requests'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


class LocalFile(Base):
    __tablename__ = 'local_files'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(Integer)
    disk_name: Mapped[str] = mapped_column(String(100))

metadata = Base.metadata
