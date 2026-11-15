"""Explicit LSX release and append-only machine assignments. No historical inference."""
from alembic import op
import sqlalchemy as sa

revision='015'
down_revision='014'


def upgrade():
    op.add_column('production_orders',sa.Column('official_code',sa.String(100)))
    op.create_unique_constraint('uq_production_official_code','production_orders',['official_code'])
    op.add_column('production_orders',sa.Column('released_at',sa.DateTime()))
    op.add_column('production_orders',sa.Column('released_by',sa.String(100),sa.ForeignKey('users.id')))
    op.add_column('production_orders',sa.Column('release_snapshot',sa.JSON()))
    op.add_column('production_orders',sa.Column('release_state',sa.String(20),nullable=False,server_default='legacy'))
    op.add_column('production_order_items',sa.Column('enabled',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('production_order_assignments',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('run_id',sa.String(100),sa.ForeignKey('production_orders.ID_Lenh_SX'),nullable=False),
        sa.Column('stage',sa.String(20),nullable=False),
        sa.Column('machine_id',sa.String(100),sa.ForeignKey('production_machines.id'),nullable=False),
        sa.Column('order_line_id',sa.String(100),sa.ForeignKey('order_lines.id')),
        sa.Column('started_at',sa.DateTime(),nullable=False),sa.Column('ended_at',sa.DateTime()),
        sa.Column('plan_id',sa.String(36),sa.ForeignKey('production_schedule_plans.id'),nullable=False),
        sa.Column('created_by',sa.String(100),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False))
    op.create_index('ix_assignment_machine','production_order_assignments',['machine_id','stage','ended_at'])
    op.create_index('ix_assignment_run','production_order_assignments',['run_id','ended_at'])
    op.add_column('forming_logs',sa.Column('actual_machine_id',sa.String(100)))
    op.add_column('forming_logs',sa.Column('assignment_id',sa.String(36),sa.ForeignKey('production_order_assignments.id')))


def downgrade():
    raise RuntimeError('Không tự xóa dữ liệu phát hành hoặc lịch sử phân công LSX.')
