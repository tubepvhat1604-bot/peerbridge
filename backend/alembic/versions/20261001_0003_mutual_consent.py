"""Create mutual consent connection tables.

Revision ID: 20261001_0003
Revises: 20261001_0002
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0003"
down_revision = "20261001_0002"
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

    if "connection_requests" not in existing_tables:
        op.create_table(
            "connection_requests",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("requester_id != recipient_id", name="ck_connection_requests_distinct_users"),
            sa.CheckConstraint(
                "status IN ('PENDING', 'MATCHED', 'REJECTED', 'EXPIRED')",
                name="ck_connection_requests_status",
            ),
        )

    existing_tables = _table_names()
    if "peer_matches" not in existing_tables:
        op.create_table(
            "peer_matches",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "connection_request_id",
                sa.Integer(),
                sa.ForeignKey("connection_requests.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_a_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_b_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("user_a_id < user_b_id", name="ck_peer_matches_ordered_users"),
            sa.UniqueConstraint("connection_request_id", name="uq_peer_matches_connection_request"),
            sa.UniqueConstraint("user_a_id", "user_b_id", name="uq_peer_matches_user_pair"),
        )

    _create_index_if_missing("ix_connection_requests_requester_id", "connection_requests", ["requester_id"])
    _create_index_if_missing("ix_connection_requests_recipient_id", "connection_requests", ["recipient_id"])
    _create_index_if_missing(
        "idx_connection_requests_pair_status",
        "connection_requests",
        ["requester_id", "recipient_id", "status"],
    )
    _create_index_if_missing("ix_peer_matches_user_a_id", "peer_matches", ["user_a_id"])
    _create_index_if_missing("ix_peer_matches_user_b_id", "peer_matches", ["user_b_id"])


def downgrade() -> None:
    existing_tables = _table_names()
    if "peer_matches" in existing_tables:
        op.drop_table("peer_matches")
    if "connection_requests" in existing_tables:
        op.drop_table("connection_requests")
