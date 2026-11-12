"""Add workbook-backed production and QC entities without modifying old tables."""
from alembic import op

revision = '004'
down_revision = '003'


def upgrade():
    from app.migrations.snapshots.v004 import metadata
    # Fail on collisions instead of silently accepting a different schema.
    metadata.create_all(bind=op.get_bind(), checkfirst=False)


def downgrade():
    raise RuntimeError('Restore a verified backup instead of deleting production/QC data.')
