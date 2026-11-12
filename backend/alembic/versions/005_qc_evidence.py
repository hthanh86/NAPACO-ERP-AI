"""Rename QC evidence without changing or copying stored links."""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'


def upgrade():
    op.alter_column('qc_checks', 'Hinh_Anh', new_column_name='evidence',
                    existing_type=sa.Text(), existing_nullable=True)


def downgrade():
    op.alter_column('qc_checks', 'evidence', new_column_name='Hinh_Anh',
                    existing_type=sa.Text(), existing_nullable=True)
