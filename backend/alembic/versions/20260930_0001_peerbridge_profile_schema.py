"""Create PeerBridge profile schema.

Revision ID: 20260930_0001
Revises:
Create Date: 2026-09-30
"""

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "20260930_0001"
down_revision = None
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _add_columns(table_name: str, columns: Iterable[sa.Column]) -> None:
    existing_columns = _column_names(table_name)
    for column in columns:
        if column.name not in existing_columns:
            op.add_column(table_name, column)


def _create_index_if_missing(name: str, table_name: str, columns: list[str]) -> None:
    if name not in _index_names(table_name):
        op.create_index(name, table_name, columns)


def upgrade() -> None:
    existing_tables = _table_names()

    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("email", sa.String(length=254), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False, server_default="STUDENT"),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("is_seed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("simulated_interest", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("role IN ('STUDENT', 'INSTRUCTOR')", name="ck_users_role"),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )
    else:
        _add_columns(
            "users",
            [
                sa.Column("role", sa.String(length=16), nullable=False, server_default="STUDENT"),
            ],
        )

    existing_tables = _table_names()
    if "profiles" not in existing_tables:
        op.create_table(
            "profiles",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("display_name", sa.String(length=80), nullable=False),
            sa.Column("age", sa.Integer(), nullable=False, server_default="18"),
            sa.Column("city", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("occupation", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("bio", sa.Text(), nullable=False, server_default=""),
            sa.Column("school", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("major", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("subjects", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("learning_goals", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("intent", sa.String(length=32), nullable=False, server_default="conversation"),
            sa.Column("interests", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("available_times", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("avatar_style", sa.String(length=32), nullable=False, server_default="one"),
            sa.Column("avatar_url", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("age BETWEEN 18 AND 100", name="ck_profiles_age_range"),
        )
    else:
        _add_columns(
            "profiles",
            [
                sa.Column("school", sa.String(length=120), nullable=False, server_default=""),
                sa.Column("major", sa.String(length=120), nullable=False, server_default=""),
                sa.Column("subjects", sa.JSON(), nullable=False, server_default="[]"),
                sa.Column("learning_goals", sa.JSON(), nullable=False, server_default="[]"),
            ],
        )

    existing_tables = _table_names()
    if "help_needs" not in existing_tables:
        op.create_table(
            "help_needs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("profile_user_id", sa.Integer(), sa.ForeignKey("profiles.user_id", ondelete="CASCADE"), nullable=False),
            sa.Column("topic", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("current_level", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("target_outcome", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("length(trim(topic)) BETWEEN 1 AND 120", name="ck_help_needs_topic_length"),
        )

    if "help_offers" not in existing_tables:
        op.create_table(
            "help_offers",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("profile_user_id", sa.Integer(), sa.ForeignKey("profiles.user_id", ondelete="CASCADE"), nullable=False),
            sa.Column("topic", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("proficiency_level", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("max_sessions_per_week", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("length(trim(topic)) BETWEEN 1 AND 120", name="ck_help_offers_topic_length"),
            sa.CheckConstraint("max_sessions_per_week BETWEEN 1 AND 20", name="ck_help_offers_weekly_sessions"),
        )

    if "availability" not in existing_tables:
        op.create_table(
            "availability",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("profile_user_id", sa.Integer(), sa.ForeignKey("profiles.user_id", ondelete="CASCADE"), nullable=False),
            sa.Column("day_of_week", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.Time(), nullable=False),
            sa.Column("end_time", sa.Time(), nullable=False),
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Bangkok"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_availability_day_of_week"),
            sa.CheckConstraint("start_time < end_time", name="ck_availability_time_range"),
        )

    _create_index_if_missing("ix_users_email", "users", ["email"])
    _create_index_if_missing("idx_help_needs_profile", "help_needs", ["profile_user_id", "id"])
    _create_index_if_missing("idx_help_offers_profile", "help_offers", ["profile_user_id", "id"])
    _create_index_if_missing("idx_availability_profile", "availability", ["profile_user_id", "day_of_week", "start_time"])


def downgrade() -> None:
    existing_tables = _table_names()
    for table_name in ("availability", "help_offers", "help_needs"):
        if table_name in existing_tables:
            op.drop_table(table_name)
