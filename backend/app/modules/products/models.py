from sqlalchemy import String, Numeric, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


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
