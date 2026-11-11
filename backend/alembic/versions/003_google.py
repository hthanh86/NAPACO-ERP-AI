from alembic import op
import sqlalchemy as sa
revision='003'
down_revision='002'


def upgrade():
    op.create_table('google_credentials',sa.Column('user_id',sa.String(100),sa.ForeignKey('users.id'),primary_key=True),
      sa.Column('subject',sa.String(255),nullable=False),sa.Column('encrypted_access',sa.Text(),nullable=False),
      sa.Column('encrypted_refresh',sa.Text(),nullable=True),sa.Column('expires_at',sa.DateTime(),nullable=False),
      sa.Column('scopes',sa.Text(),nullable=False))
    op.create_table('google_oauth_states',sa.Column('state_hash',sa.String(64),primary_key=True),
      sa.Column('verifier',sa.String(200),nullable=False),sa.Column('expires_at',sa.DateTime(),nullable=False))


def downgrade():
    raise RuntimeError('Restore a verified backup instead of deleting credentials.')
