"""Technical QC queue and staging manifests; never stores file bytes or OAuth tokens."""
from datetime import datetime
from sqlalchemy import String, Integer, JSON, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.modules.qc.models import QualityCheck


class QCJob(Base):
    __tablename__ = 'QC_JOBS'
    __table_args__ = (UniqueConstraint('QC_ID',name='uq_qc_job_qc'),
        Index('ix_qc_job_claim','STATUS','AVAILABLE_AT','LEASE_UNTIL'),)
    id: Mapped[str] = mapped_column('JOB_ID',String(36),primary_key=True)
    qc_id: Mapped[str | None] = mapped_column('QC_ID',ForeignKey(QualityCheck.id))
    owner_id: Mapped[str] = mapped_column('OWNER_ID',ForeignKey('users.id'))
    status: Mapped[str] = mapped_column('STATUS',String(20),default='STAGING')
    current_step: Mapped[str] = mapped_column('CURRENT_STEP',String(60),default='staging')
    attempts: Mapped[int] = mapped_column('ATTEMPTS',Integer,default=0)
    last_error: Mapped[str] = mapped_column('LAST_ERROR',String(2000),default='')
    created_at: Mapped[datetime] = mapped_column('CREATED_AT',DATETIME(fsp=6),default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column('UPDATED_AT',DATETIME(fsp=6),default=datetime.utcnow)
    available_at: Mapped[datetime] = mapped_column('AVAILABLE_AT',DATETIME(fsp=6),default=datetime.utcnow)
    lease_until: Mapped[datetime | None] = mapped_column('LEASE_UNTIL',DATETIME(fsp=6))
    lease_token: Mapped[str | None] = mapped_column('LEASE_TOKEN',String(36))
    manifest: Mapped[list] = mapped_column('MANIFEST',JSON,default=list)
    metrics: Mapped[dict] = mapped_column('METRICS',JSON,default=dict)
    revision: Mapped[str | None] = mapped_column('REVISION',String(64))
    google_subject: Mapped[str | None] = mapped_column('GOOGLE_SUBJECT',String(255))
