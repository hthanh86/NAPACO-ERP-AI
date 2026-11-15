"""Freeze plan context and explicitly close daily baselines. No new LSX."""
from alembic import op
import sqlalchemy as sa
revision='014'
down_revision='013'


def upgrade():
    op.add_column('production_schedule_plans',sa.Column('context',sa.JSON(),nullable=True))
    op.create_table('production_schedule_days',
        sa.Column('day',sa.Date(),primary_key=True),sa.Column('scope',sa.String(40),primary_key=True),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('initial_plan_id',sa.String(36),sa.ForeignKey('production_schedule_plans.id')),
        sa.Column('initial_closed_at',sa.DateTime()),
        sa.Column('initial_closed_by',sa.String(100),sa.ForeignKey('users.id')),
        sa.Column('update_plan_id',sa.String(36),sa.ForeignKey('production_schedule_plans.id')),
        sa.Column('updated_at',sa.DateTime(),nullable=False),
        sa.Column('updated_by',sa.String(100),sa.ForeignKey('users.id')))


def downgrade():
    raise RuntimeError('Không tự xóa bản chốt và lịch sử kế hoạch theo ngày.')
