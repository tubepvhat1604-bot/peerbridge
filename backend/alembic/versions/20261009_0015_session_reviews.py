"""Add session_reviews: tóm tắt phiên học và chấm tuân thủ Socratic."""

from alembic import op
from app.session_review.schema import SCHEMA

revision = "20261009_0015"
down_revision = "20261007_0014"
branch_labels = None
depends_on = None


def upgrade():
    for statement in filter(None, (s.strip() for s in SCHEMA.split(";"))):
        op.execute(statement)


def downgrade():
    op.execute("DROP TABLE IF EXISTS session_reviews")
