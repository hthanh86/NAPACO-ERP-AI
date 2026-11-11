from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


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
