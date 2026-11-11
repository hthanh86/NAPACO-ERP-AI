from sqlalchemy import String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Customer(Base):
    __tablename__ = 'customers'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    address: Mapped[str] = mapped_column(Text, default='')
    contact: Mapped[str] = mapped_column(String(500), default='')
    phone: Mapped[str] = mapped_column(String(200), default='')
    source: Mapped[dict] = mapped_column(JSON, default=dict)
