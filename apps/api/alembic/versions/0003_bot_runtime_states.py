"""add observable runtime states"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name=="postgresql":
        op.execute("ALTER TYPE botstatus ADD VALUE IF NOT EXISTS 'STOPPING'")
        op.execute("ALTER TYPE botstatus ADD VALUE IF NOT EXISTS 'RECONNECTING'")


def downgrade():
    pass
