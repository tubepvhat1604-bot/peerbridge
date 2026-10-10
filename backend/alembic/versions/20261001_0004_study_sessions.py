"""Create study session domain tables.

Revision ID: 20261001_0004
Revises: 20261001_0003
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0004"
down_revision = "20261001_0003"
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

    if "study_sessions" not in existing_tables:
        op.create_table(
            "study_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("peer_match_id", sa.Integer(), sa.ForeignKey("peer_matches.id", ondelete="CASCADE"), nullable=False),
            sa.Column("learner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("helper_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("topic", sa.String(length=120), nullable=False),
            sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("learner_id != helper_id", name="ck_study_sessions_distinct_participants"),
            sa.CheckConstraint(
                "scheduled_start IS NULL OR scheduled_end IS NULL OR scheduled_end > scheduled_start",
                name="ck_study_sessions_schedule_order",
            ),
            sa.CheckConstraint("length(trim(topic)) BETWEEN 1 AND 120", name="ck_study_sessions_topic_length"),
        )

    existing_tables = _table_names()
    if "chat_messages" not in existing_tables:
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "session_id",
                sa.Integer(),
                sa.ForeignKey("study_sessions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("length(trim(content)) BETWEEN 1 AND 2000", name="ck_chat_messages_content_length"),
        )

    _create_index_if_missing("ix_study_sessions_peer_match_id", "study_sessions", ["peer_match_id"])
    _create_index_if_missing("ix_study_sessions_learner_id", "study_sessions", ["learner_id"])
    _create_index_if_missing("ix_study_sessions_helper_id", "study_sessions", ["helper_id"])
    _create_index_if_missing("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    _create_index_if_missing("ix_chat_messages_sender_id", "chat_messages", ["sender_id"])


def downgrade() -> None:
    existing_tables = _table_names()
    if "chat_messages" in existing_tables:
        op.drop_table("chat_messages")
    if "study_sessions" in existing_tables:
        op.drop_table("study_sessions")
