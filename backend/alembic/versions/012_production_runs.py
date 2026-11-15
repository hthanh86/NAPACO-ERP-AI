"""Extend current LSX/logs for grouped runs, closed shifts and product lineage."""
from alembic import op
import sqlalchemy as sa
revision='012'
down_revision='011'


def upgrade():
    op.add_column('production_orders',sa.Column('standard_id',sa.String(36)))
    op.create_foreign_key('fk_run_standard','production_orders','production_standards',['standard_id'],['id'])
    op.add_column('production_orders',sa.Column('run_snapshot',sa.JSON()))
    op.add_column('production_orders',sa.Column('version',sa.Integer(),nullable=False,server_default='1'))
    op.add_column('production_orders',sa.Column('parent_run_id',sa.String(100)))
    op.create_foreign_key('fk_run_parent','production_orders','production_orders',['parent_run_id'],['ID_Lenh_SX'])
    op.create_index('ix_run_group','production_orders',['Ma_Nhom_Ghep'])
    for column in [sa.Column('shift_start',sa.DateTime()),sa.Column('shift_end',sa.DateTime()),
                   sa.Column('shift_snapshot',sa.JSON()),sa.Column('version',sa.Integer(),nullable=False,server_default='1')]:
        op.add_column('forming_logs',column)
    op.create_index('ix_shift_run_end','forming_logs',['ID_Lenh_SX','shift_end'])
    op.create_table('production_order_items',
        sa.Column('run_id',sa.String(100),sa.ForeignKey('production_orders.ID_Lenh_SX'),primary_key=True),
        sa.Column('order_line_id',sa.String(100),sa.ForeignKey('order_lines.id'),primary_key=True),
        sa.Column('product_id',sa.String(100),sa.ForeignKey('products.id'),nullable=False),
        sa.Column('planned_qty',sa.Numeric(24,8),nullable=False),sa.Column('completed_qty',sa.Numeric(24,8),nullable=False),
        sa.Column('cavity',sa.Integer(),nullable=False),sa.Column('snapshot',sa.JSON(),nullable=False))
    op.create_index('ix_run_item_order_line','production_order_items',['order_line_id'])
    op.create_table('production_run_materials',
        sa.Column('run_id',sa.String(100),sa.ForeignKey('production_orders.ID_Lenh_SX'),primary_key=True),
        sa.Column('allocation_id',sa.String(36),sa.ForeignKey('material_allocations.id'),primary_key=True),
        sa.Column('planned_kg',sa.Numeric(24,8),nullable=False),sa.Column('issued_kg',sa.Numeric(24,8),nullable=False))
    op.create_table('production_shift_items',
        sa.Column('log_id',sa.String(100),sa.ForeignKey('forming_logs.ID_Nhat_Ky'),primary_key=True),
        sa.Column('order_line_id',sa.String(100),sa.ForeignKey('order_lines.id'),primary_key=True),
        sa.Column('good_qty',sa.Numeric(24,8),nullable=False),sa.Column('ng_qty',sa.Numeric(24,8),nullable=False))
    op.create_table('production_shift_materials',
        sa.Column('log_id',sa.String(100),sa.ForeignKey('forming_logs.ID_Nhat_Ky'),primary_key=True),
        sa.Column('receipt_id',sa.String(100),sa.ForeignKey('film_receipts.id'),primary_key=True),
        *[sa.Column(name,sa.Numeric(24,8),nullable=False) for name in ['opening_kg','input_kg','output_kg','consumed_kg','closing_kg']],
        sa.Column('movements',sa.JSON(),nullable=False))
    op.create_table('production_downstream_items',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('cut_id',sa.String(100),sa.ForeignKey('cutting_logs.CUT_ID')),
        sa.Column('edge_id',sa.String(100),sa.ForeignKey('eb_logs.EB_ID')),
        sa.Column('forming_log_id',sa.String(100),sa.ForeignKey('forming_logs.ID_Nhat_Ky'),nullable=False),
        sa.Column('order_line_id',sa.String(100),sa.ForeignKey('order_lines.id'),nullable=False),
        sa.Column('stage',sa.String(20),nullable=False),
        *[sa.Column(name,sa.Numeric(24,8),nullable=False) for name in ['input_qty','good_qty','ng_qty']],
        sa.Column('snapshot',sa.JSON(),nullable=False),
        sa.CheckConstraint('(cut_id IS NOT NULL AND edge_id IS NULL) OR (cut_id IS NULL AND edge_id IS NOT NULL)',name='ck_downstream_one_log'))
    op.create_index('ix_downstream_source','production_downstream_items',['forming_log_id','order_line_id','stage'])
    # Do not rewrite historic statuses, IDs, DH_ID or missing source links.
    # Global weekly defaults use existing system_settings, created only by an explicit save.


def downgrade():
    raise RuntimeError('Không tự xóa lịch sử lệnh/ca/truy vết. Cần phương án đối soát riêng.')
