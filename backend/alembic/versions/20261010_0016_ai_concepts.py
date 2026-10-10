"""Cho phép domain "ai" trong bảng concepts (danh mục bài slide khóa AICB)."""

from alembic import op
from app.onboarding.schema import allow_ai_domain

revision = "20261010_0016"
down_revision = "20261009_0015"
branch_labels = None
depends_on = None


def upgrade():
    allow_ai_domain(op.get_bind().connection.driver_connection)


def downgrade():
    op.execute("DELETE FROM concepts WHERE domain='ai'")
