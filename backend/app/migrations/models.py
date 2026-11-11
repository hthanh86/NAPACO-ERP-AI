from datetime import datetime
from sqlalchemy import String, Integer, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


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
