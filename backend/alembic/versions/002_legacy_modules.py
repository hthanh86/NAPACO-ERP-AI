"""Relational film modules and local compatibility metadata."""
from alembic import op
revision = '002'
down_revision = '001'


def upgrade():
    from app.migrations.snapshots.v002 import metadata
    metadata.create_all(bind=op.get_bind())


def downgrade():
    raise RuntimeError('Restore a backup instead of deleting business tables.')
