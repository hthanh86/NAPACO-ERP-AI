"""Registered source spreadsheets, separate from QC result/form snapshots."""
from datetime import datetime
from sqlalchemy import String, Integer, ForeignKey, Enum, JSON, Boolean
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class QCTemplate(Base):
    __tablename__ = 'QC_TEMPLATES'
    id: Mapped[str] = mapped_column('TEMPLATE_ID', String(36), primary_key=True)
    form_code: Mapped[str] = mapped_column('FORM_CODE', String(100), unique=True)
    form_name: Mapped[str] = mapped_column('FORM_NAME', String(300))
    check_type: Mapped[str] = mapped_column('CHECK_TYPE', String(50))
    object_type: Mapped[str | None] = mapped_column('OBJECT_TYPE', String(50))
    product_id: Mapped[str | None] = mapped_column('PRODUCT_ID', ForeignKey('products.id'))
    spreadsheet_id: Mapped[str] = mapped_column('SPREADSHEET_ID', String(255))
    sheet_id: Mapped[int] = mapped_column('SHEET_ID', Integer)
    version: Mapped[int] = mapped_column('VERSION', Integer, default=1)
    status: Mapped[str] = mapped_column('STATUS', Enum('DRAFT', 'ACTIVE', 'INACTIVE'), default='DRAFT')
    created_by: Mapped[str] = mapped_column('CREATED_BY', ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column('CREATED_AT', DATETIME(fsp=6), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column('UPDATED_AT', DATETIME(fsp=6), default=datetime.utcnow)
    field_mapping: Mapped[dict | None] = mapped_column('FIELD_MAPPING', JSON)
    source_snapshot: Mapped[dict | None] = mapped_column('SOURCE_SNAPSHOT', JSON)
    source_hash: Mapped[str | None] = mapped_column('SOURCE_HASH', String(64))
    approved_by: Mapped[str | None] = mapped_column('APPROVED_BY', ForeignKey('users.id'))
    approved_at: Mapped[datetime | None] = mapped_column('APPROVED_AT', DATETIME(fsp=6))
    source_checked_at: Mapped[datetime | None] = mapped_column('SOURCE_CHECKED_AT', DATETIME(fsp=6))
    source_matches: Mapped[bool | None] = mapped_column('SOURCE_MATCHES', Boolean)
