"""Create human-in-the-loop moderation tables.

Revision ID: 20261001_0005
Revises: 20261001_0004
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0005"
down_revision = "20261001_0004"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(name: str, table_name: str, columns: list[str]) -> None:
    if name not in _index_names(table_name):
        op.create_index(name, table_name, columns)


def upgrade() -> None:
    existing_tables = _table_names()

    if "moderation_events" not in existing_tables:
        op.create_table(
            "moderation_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("study_sessions.id"), nullable=False),
            sa.Column("message_id", sa.Integer(), sa.ForeignKey("chat_messages.id"), nullable=False),
            sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("agent_action", sa.String(length=16), nullable=False),
            sa.Column("risk_score", sa.Float(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("guidance", sa.Text(), nullable=True),
            sa.Column("needs_human_review", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("context", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "agent_action IN ('ALLOW', 'GUIDE', 'WARN', 'BLOCK', 'ESCALATE')",
                name="ck_moderation_events_agent_action",
            ),
            sa.CheckConstraint("risk_score >= 0 AND risk_score <= 1", name="ck_moderation_events_risk_score"),
            sa.CheckConstraint(
                "length(trim(reason)) BETWEEN 1 AND 1000",
                name="ck_moderation_events_reason_length",
            ),
        )

    existing_tables = _table_names()
    if "instructor_reviews" not in existing_tables:
        op.create_table(
            "instructor_reviews",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "moderation_event_id",
                sa.Integer(),
                sa.ForeignKey("moderation_events.id"),
                nullable=False,
                unique=True,
            ),
            sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("review_action", sa.String(length=16), nullable=False),
            sa.Column("override_action", sa.String(length=16), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "review_action IN ('APPROVE', 'OVERRIDE', 'INTERVENE')",
                name="ck_instructor_reviews_review_action",
            ),
            sa.CheckConstraint(
                "override_action IS NULL OR override_action IN ('ALLOW', 'GUIDE', 'WARN', 'BLOCK', 'ESCALATE')",
                name="ck_instructor_reviews_override_action",
            ),
        )

    _create_index_if_missing("ix_moderation_events_session_id", "moderation_events", ["session_id"])
    _create_index_if_missing("ix_moderation_events_message_id", "moderation_events", ["message_id"])
    _create_index_if_missing("ix_moderation_events_sender_id", "moderation_events", ["sender_id"])
    _create_index_if_missing("ix_instructor_reviews_moderation_event_id", "instructor_reviews", ["moderation_event_id"])
    _create_index_if_missing("ix_instructor_reviews_instructor_id", "instructor_reviews", ["instructor_id"])


def downgrade() -> None:
    existing_tables = _table_names()
    if "instructor_reviews" in existing_tables:
        op.drop_table("instructor_reviews")
    if "moderation_events" in existing_tables:
        op.drop_table("moderation_events")
