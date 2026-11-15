"""Stage 1 planning foundations. Explicit approval required before local application."""
from alembic import op
import sqlalchemy as sa
revision = '010'
down_revision = '009'


def upgrade():
    op.create_table('production_machines',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('max_width_mm', sa.Numeric(16,4)), sa.Column('max_pull_mm', sa.Numeric(16,4)),
        sa.Column('notes', sa.String(2000), nullable=False),
        sa.Column('calendar', sa.JSON(), nullable=False), sa.Column('version', sa.Integer(), nullable=False))
    op.create_table('production_standards',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('code', sa.String(100), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('machine_id', sa.String(100), sa.ForeignKey('production_machines.id'), nullable=False),
        sa.Column('material_id', sa.String(100), sa.ForeignKey('film_materials.id'), nullable=False),
        sa.Column('mold_id', sa.String(100), nullable=False), sa.Column('name', sa.String(200), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False), sa.Column('parameters', sa.JSON(), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(100), sa.ForeignKey('users.id'), nullable=False),
        sa.UniqueConstraint('code','revision',name='uq_production_standard_revision'))
    op.create_table('production_standard_items',
        sa.Column('standard_id',sa.String(36),sa.ForeignKey('production_standards.id'),primary_key=True),
        sa.Column('product_id',sa.String(100),sa.ForeignKey('products.id'),primary_key=True),
        sa.Column('cavity',sa.Integer(),nullable=False),sa.Column('edge',sa.Boolean(),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False))
    op.create_table('production_calendar_exceptions',
        sa.Column('machine_id',sa.String(100),sa.ForeignKey('production_machines.id'),primary_key=True),
        sa.Column('day',sa.Date(),primary_key=True),sa.Column('windows',sa.JSON(),nullable=False),
        sa.Column('note',sa.String(500),nullable=False))
    # Preserve source IDs. Ambiguous forming types require classification by an operator.
    connection = op.get_bind()
    source = sa.table('source_rows', sa.column('book'),sa.column('sheet'),sa.column('row_number'),sa.column('cells',sa.JSON()))
    rows = connection.execute(sa.select(source.c.cells).where(source.c.book=='master',
        source.c.sheet=='06.DM_May').order_by(source.c.row_number)).scalars().all()
    if not rows:
        return
    headers = rows[0]
    required = ['Ma_May','Ten_May','Loai_May','Trang_Thai']
    if not all(key in headers for key in required):
        raise RuntimeError('Danh mục máy nguồn thiếu tiêu đề. Không tự suy đoán cột.')
    machines = sa.table('production_machines', *[sa.column(key, typ) for key,typ in [
        ('id',sa.String()),('name',sa.String()),('kind',sa.String()),('status',sa.String()),
        ('notes',sa.String()),('calendar',sa.JSON()),('version',sa.Integer())]])
    for cells in rows[1:]:
        row = dict(zip(headers,cells))
        if not row.get('Ma_May'):
            continue
        state = {'Sẵn sàng':'ready','Đang chạy':'running','Đang bảo dưỡng':'maintenance','Lỗi đột xuất':'fault'}.get(row.get('Trang_Thai'),'inactive')
        connection.execute(machines.insert().values(id=str(row['Ma_May']),name=row.get('Ten_May') or row['Ma_May'],
            kind='cutting' if row.get('Loai_May')=='Bế cắt' else 'unclassified',status=state,
            notes='Nguồn: '+str(row.get('Loai_May') or ''),calendar={},version=1))


def downgrade():
    raise RuntimeError('Không tự xóa dữ liệu nền hoặc lịch sử định mức. Cần kế hoạch và sao lưu riêng.')
