"""Signed handover lifecycle; leave all historical movements unchanged."""
from alembic import op
import sqlalchemy as sa
revision='016'
down_revision='015'


def upgrade():
    op.create_table('material_handovers',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('run_id',sa.String(100),sa.ForeignKey('production_orders.ID_Lenh_SX'),nullable=False),
        sa.Column('allocation_id',sa.String(36),sa.ForeignKey('material_allocations.id')),
        sa.Column('source_issue_id',sa.String(100),sa.ForeignKey('film_movements.id')),
        sa.Column('mode',sa.String(20),nullable=False),sa.Column('quantity',sa.Numeric(24,8),nullable=False),
        sa.Column('state',sa.String(24),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('movement_id',sa.String(100),sa.ForeignKey('film_movements.id'),unique=True),
        sa.Column('snapshot',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(100),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('issued_by',sa.String(100),sa.ForeignKey('users.id')),sa.Column('issued_at',sa.DateTime()),
        sa.Column('received_by',sa.String(100),sa.ForeignKey('users.id')),sa.Column('received_at',sa.DateTime()),
        sa.Column('issue_signature',sa.JSON()),sa.Column('receipt_signature',sa.JSON()),
        sa.CheckConstraint('quantity > 0',name='ck_handover_positive'))
    for name,columns in [('run',['run_id','state']),('allocation',['allocation_id','state']),('source',['source_issue_id','state'])]:
        op.create_index('ix_handover_'+name+'_state','material_handovers',columns)


def downgrade():
    raise RuntimeError('Không tự xóa chứng từ và chữ ký bàn giao NVL.')
