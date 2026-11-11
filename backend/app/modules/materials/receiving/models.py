from datetime import date
from decimal import Decimal
from sqlalchemy import String, Text, Numeric, Date, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


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
