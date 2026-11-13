from app.core.database import Base
from app.migrations.snapshots.v004 import qc_checks
from sqlalchemy import Column, String, JSON, ForeignKey


class QualityCheck(Base):
    __tablename__ = 'qc_checks'
    __table__ = qc_checks.to_metadata(Base.metadata)
    # Preserve the existing Python/API image_url attribute; MySQL uses evidence.
    __table__.c.image_url.name = 'evidence'
    __table__.append_column(Column('DRIVE_FOLDER_ID', String(255), key='drive_folder_id'))
    __table__.append_column(Column('FORM_DATA', JSON, key='form_data'))
    __table__.append_column(Column('TEMPLATE_ID', String(36), ForeignKey('QC_TEMPLATES.TEMPLATE_ID'), key='template_id'))
