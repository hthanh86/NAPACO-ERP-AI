"""Approved mapping snapshots and nullable QC template reference; preserve history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = '008'
down_revision = '007'


def upgrade():
    for column in [sa.Column('FIELD_MAPPING', sa.JSON()), sa.Column('SOURCE_SNAPSHOT', sa.JSON()),
                   sa.Column('SOURCE_HASH', sa.String(64)), sa.Column('APPROVED_BY', sa.String(100)),
                   sa.Column('APPROVED_AT', DATETIME(fsp=6)), sa.Column('SOURCE_CHECKED_AT', DATETIME(fsp=6)),
                   sa.Column('SOURCE_MATCHES', sa.Boolean())]:
        op.add_column('QC_TEMPLATES', column)
    op.create_foreign_key('fk_qc_template_approver', 'QC_TEMPLATES', 'users', ['APPROVED_BY'], ['id'])
    op.add_column('qc_checks', sa.Column('TEMPLATE_ID', sa.String(36), nullable=True))
    op.create_foreign_key('fk_qc_check_template', 'qc_checks', 'QC_TEMPLATES', ['TEMPLATE_ID'], ['TEMPLATE_ID'])


def downgrade():
    raise RuntimeError('Không xóa mapping và tham chiếu hồ sơ QC. Cần sao lưu và migration riêng.')
