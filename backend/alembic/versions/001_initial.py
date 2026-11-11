"""Initial order-management schema."""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None


def upgrade():
    # Frozen initial schema: later model changes require a new revision.
    from app.migrations.snapshots.v001 import metadata
    metadata.create_all(bind=op.get_bind())


def downgrade():
    raise RuntimeError('Automatic destructive downgrade is disabled. Restore a verified backup instead.')
