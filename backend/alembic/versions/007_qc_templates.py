"""Register QC source templates without modifying existing QC records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = '007'
down_revision = '006'


def upgrade():
    op.create_table('QC_TEMPLATES',
        sa.Column('TEMPLATE_ID', sa.String(36), primary_key=True),
        sa.Column('FORM_CODE', sa.String(100), nullable=False, unique=True),
        sa.Column('FORM_NAME', sa.String(300), nullable=False),
        sa.Column('CHECK_TYPE', sa.String(50), nullable=False),
        sa.Column('OBJECT_TYPE', sa.String(50), nullable=True),
        sa.Column('PRODUCT_ID', sa.String(100), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('SPREADSHEET_ID', sa.String(255), nullable=False),
        sa.Column('SHEET_ID', sa.Integer(), nullable=False),
        sa.Column('VERSION', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('STATUS', sa.Enum('DRAFT', 'ACTIVE', 'INACTIVE'), nullable=False, server_default='DRAFT'),
        sa.Column('CREATED_BY', sa.String(100), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('CREATED_AT', DATETIME(fsp=6), nullable=False),
        sa.Column('UPDATED_AT', DATETIME(fsp=6), nullable=False))


def downgrade():
    raise RuntimeError('Không tự động xóa template đã đăng ký. Cần sao lưu và migration riêng.')
