from decimal import Decimal
from sqlalchemy import String, Text, Numeric, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


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
