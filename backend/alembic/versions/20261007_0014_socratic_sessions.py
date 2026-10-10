"""Persist Socratic tutoring progress per learner and Study Room."""

from alembic import op
import sqlalchemy as sa

revision = "20261007_0014"
down_revision = "20261007_0013"
branch_labels = None
depends_on = None


def upgrade():
    if "socratic_sessions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "socratic_sessions",
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("study_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("original_question", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False, server_default=""),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_guidance", sa.Text()),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )


def downgrade():
    if "socratic_sessions" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("socratic_sessions")
