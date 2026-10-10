"""Add shared AI cost ledger (plan task generation, match reranking)."""

from alembic import op
from app.loop.ai_budget import SCHEMA

revision = "20261007_0013"
down_revision = "20261007_0012"
branch_labels = None
depends_on = None


def upgrade():
    for statement in filter(None, (s.strip() for s in SCHEMA.split(";"))):
        op.execute(statement)


def downgrade():
    op.execute("DROP TABLE IF EXISTS ai_usage")
