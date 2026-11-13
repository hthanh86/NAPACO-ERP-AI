"""Shared configuration stored in MySQL; no public settings editor."""
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class SystemSetting(Base):
    __tablename__ = 'system_settings'
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


def get_setting(db, key):
    setting = db.get(SystemSetting, key)
    return setting.value.strip() if setting else ''
