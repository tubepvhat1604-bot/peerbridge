"""Add isolated Plan/Coach tables without replacing existing user or pair tables."""

from alembic import op
from app.plan_tables import PLAN_TABLES

revision = "20261006_0010"
down_revision = "20261006_0009"
branch_labels = None
depends_on = None


def upgrade():
    for table in PLAN_TABLES:
        table.create(op.get_bind(), checkfirst=True)


def downgrade():
    for table in reversed(PLAN_TABLES):
        table.drop(op.get_bind(), checkfirst=True)
