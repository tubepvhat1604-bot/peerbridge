"""Add AI Vision check-in tables (vi_checkins, vi_reactions, vi_nudges)."""

from alembic import op
from app.checkin import models  # noqa: F401
from app.checkin.db import Base

revision = "20261006_0011"
down_revision = "20261006_0010"
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade():
    Base.metadata.drop_all(op.get_bind(), checkfirst=True)
