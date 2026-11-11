from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class GoogleCredential(Base):
    __tablename__='google_credentials'
    user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
    subject:Mapped[str]=mapped_column(String(255))
    encrypted_access:Mapped[str]=mapped_column(Text)
    encrypted_refresh:Mapped[str|None]=mapped_column(Text)
    expires_at:Mapped[datetime]=mapped_column(DateTime)
    scopes:Mapped[str]=mapped_column(Text)


class GoogleOAuthState(Base):
    __tablename__='google_oauth_states'
    state_hash:Mapped[str]=mapped_column(String(64),primary_key=True)
    verifier:Mapped[str]=mapped_column(String(200))
    expires_at:Mapped[datetime]=mapped_column(DateTime)
