"""Stage 2: reservation balance and links to the existing physical movement ledger."""
from alembic import op
import sqlalchemy as sa
revision = '011'
down_revision = '010'


def upgrade():
    op.create_table('material_allocations',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('receipt_id',sa.String(100),sa.ForeignKey('film_receipts.id'),nullable=False),
        sa.Column('order_line_id',sa.String(100),sa.ForeignKey('order_lines.id'),nullable=False),
        sa.Column('standard_id',sa.String(36),sa.ForeignKey('production_standards.id'),nullable=False),
        sa.Column('held_kg',sa.Numeric(24,8),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('note',sa.String(1000),nullable=False),
        sa.Column('created_by',sa.String(100),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.CheckConstraint('held_kg >= 0',name='ck_material_allocation_held'))
    op.create_index('ix_allocation_receipt','material_allocations',['receipt_id'])
    op.create_index('ix_allocation_order_line','material_allocations',['order_line_id'])
    op.create_table('material_allocation_movements',
        sa.Column('movement_id',sa.String(100),sa.ForeignKey('film_movements.id'),primary_key=True),
        sa.Column('allocation_id',sa.String(36),sa.ForeignKey('material_allocations.id'),nullable=False),
        sa.Column('issue_id',sa.String(100),sa.ForeignKey('film_movements.id')),
        sa.Column('mode',sa.String(20),nullable=False),sa.Column('transfer_id',sa.String(36)),
        sa.Column('snapshot',sa.JSON(),nullable=False))
    op.create_index('ix_allocation_movement_allocation','material_allocation_movements',['allocation_id'])
    op.create_index('ix_allocation_movement_issue','material_allocation_movements',['issue_id'])
    op.create_index('ix_material_allocation_movements_transfer_id','material_allocation_movements',['transfer_id'])
    # No backfill: historic issue/return rows have no reliable CTDH allocation lineage.


def downgrade():
    raise RuntimeError('Không tự xóa giữ nhựa hoặc truy vết giao dịch. Cần kế hoạch đối soát và sao lưu.')
