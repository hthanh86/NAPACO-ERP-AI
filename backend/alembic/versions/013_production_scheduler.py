"""Backend scheduler snapshots and stop control. No replacement LSX model."""
from alembic import op
import sqlalchemy as sa
revision='013'
down_revision='012'


def upgrade():
    op.create_table('production_schedule_plans',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('version',sa.Integer(),nullable=False,unique=True),
        sa.Column('request',sa.JSON(),nullable=False),sa.Column('result',sa.JSON(),nullable=False),
        sa.Column('source_hash',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('created_by',sa.String(100),sa.ForeignKey('users.id'),nullable=False))
    op.create_table('production_run_stops',
        sa.Column('id',sa.String(100),primary_key=True),
        sa.Column('run_id',sa.String(100),sa.ForeignKey('production_orders.ID_Lenh_SX'),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),sa.Column('started_at',sa.DateTime(),nullable=False),
        sa.Column('duration_seconds',sa.Integer()),sa.Column('hold_machine',sa.Boolean(),nullable=False),
        sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('note',sa.String(2000),nullable=False))
    op.create_index('ix_run_stop_active','production_run_stops',['run_id','enabled'])


def downgrade():
    raise RuntimeError('Không tự xóa bản kế hoạch và lịch sử dừng máy.')
