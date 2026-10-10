"""Explicit instructor and course assignments; no implicit grants for existing users."""
import sqlalchemy as sa
from alembic import op

revision = "20261003_0006"
down_revision = "20261001_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "moderation_quota" not in existing:
        op.create_table("moderation_quota",
            sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("window_start", sa.String(40), primary_key=True),
            sa.Column("request_count", sa.Integer(), nullable=False))
    if "session_instructors" not in existing:
        op.create_table("session_instructors",
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("study_sessions.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True))
    if "course_memberships" not in existing:
        op.create_table("course_memberships",
            sa.Column("course_id", sa.String(120), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True))
    if "session_courses" not in existing:
        op.create_table("session_courses",
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("study_sessions.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("course_id", sa.String(120), nullable=False))


def downgrade() -> None:
    for name in ("moderation_quota", "session_courses", "course_memberships", "session_instructors"):
        op.drop_table(name)
