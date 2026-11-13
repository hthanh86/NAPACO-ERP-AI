"""Add QC form snapshots and folder reference; preserve every legacy column."""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = '005'


def upgrade():
    settings = op.create_table('system_settings',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('value', sa.Text(), nullable=False))
    op.bulk_insert(settings, [{'key': 'QC_ROOT_FOLDER_ID', 'value': '1N_sNZGMv2LyPE1mowNGRTa9KW6A2kmnz'}])
    op.add_column('qc_checks', sa.Column('DRIVE_FOLDER_ID', sa.String(255), nullable=True))
    op.add_column('qc_checks', sa.Column('FORM_DATA', sa.JSON(), nullable=True))


def downgrade():
    # Never silently discard signed forms or the company configuration.
    raise RuntimeError('Không tự động xóa dữ liệu form QC. Hãy xuất hồ sơ và lập migration phục hồi riêng.')
