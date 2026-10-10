"""Add in-app notifications table."""

from alembic import op
from app.home.notifications import SCHEMA

revision = "20261007_0012"
down_revision = "20261006_0011"
branch_labels = None
depends_on = None


def upgrade():
    for statement in filter(None, (s.strip() for s in SCHEMA.split(";"))):
        op.execute(statement)


def downgrade():
    op.execute("DROP TABLE IF EXISTS notifications")
