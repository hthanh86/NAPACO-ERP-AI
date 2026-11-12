from app.core.database import Base
from app.migrations.snapshots.v004 import qc_checks


class QualityCheck(Base):
    __tablename__ = 'qc_checks'
    __table__ = qc_checks.to_metadata(Base.metadata)
