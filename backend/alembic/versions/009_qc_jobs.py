"""Durable single-host staging and leased QC work queue; QC history stays intact."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME
revision='009'
down_revision='008'


def upgrade():
    op.create_table('QC_JOBS',
        sa.Column('JOB_ID',sa.String(36),primary_key=True),
        sa.Column('QC_ID',sa.String(100),sa.ForeignKey('qc_checks.QC_ID'),nullable=True),
        sa.Column('OWNER_ID',sa.String(100),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('STATUS',sa.String(20),nullable=False),
        sa.Column('CURRENT_STEP',sa.String(60),nullable=False),
        sa.Column('ATTEMPTS',sa.Integer(),nullable=False),
        sa.Column('LAST_ERROR',sa.String(2000),nullable=False),
        sa.Column('CREATED_AT',DATETIME(fsp=6),nullable=False),
        sa.Column('UPDATED_AT',DATETIME(fsp=6),nullable=False),
        sa.Column('AVAILABLE_AT',DATETIME(fsp=6),nullable=False),
        sa.Column('LEASE_UNTIL',DATETIME(fsp=6)),sa.Column('LEASE_TOKEN',sa.String(36)),
        sa.Column('MANIFEST',sa.JSON(),nullable=False),sa.Column('METRICS',sa.JSON(),nullable=False),
        sa.Column('REVISION',sa.String(64)),sa.Column('GOOGLE_SUBJECT',sa.String(255)),sa.UniqueConstraint('QC_ID',name='uq_qc_job_qc'))
    op.create_index('ix_qc_job_claim','QC_JOBS',['STATUS','AVAILABLE_AT','LEASE_UNTIL'])


def downgrade():
    raise RuntimeError('Không tự xóa queue hoặc manifest staging. Cần sao lưu và kế hoạch riêng.')
