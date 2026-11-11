from decimal import Decimal
from sqlalchemy import String, Numeric, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


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
