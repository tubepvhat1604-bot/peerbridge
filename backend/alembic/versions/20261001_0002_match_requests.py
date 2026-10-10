"""Create match request persistence tables.

Revision ID: 20261001_0002
Revises: 20260930_0001
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0002"
down_revision = "20260930_0001"
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

    if "match_requests" not in existing_tables:
        op.create_table(
            "match_requests",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    existing_tables = _table_names()
    if "match_candidates" not in existing_tables:
        op.create_table(
            "match_candidates",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "request_id",
                sa.Integer(),
                sa.ForeignKey("match_requests.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("total_score", sa.Float(), nullable=False),
            sa.Column("component_scores", sa.JSON(), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("total_score >= 0 AND total_score <= 100", name="ck_match_candidates_total_score"),
            sa.CheckConstraint("rank > 0", name="ck_match_candidates_rank"),
            sa.UniqueConstraint("request_id", "candidate_id", name="uq_match_candidates_request_candidate"),
            sa.UniqueConstraint("request_id", "rank", name="uq_match_candidates_request_rank"),
        )

    _create_index_if_missing("ix_match_requests_requester_id", "match_requests", ["requester_id"])
    _create_index_if_missing("ix_match_candidates_request_id", "match_candidates", ["request_id"])
    _create_index_if_missing("ix_match_candidates_candidate_id", "match_candidates", ["candidate_id"])


def downgrade() -> None:
    existing_tables = _table_names()
    if "match_candidates" in existing_tables:
        op.drop_table("match_candidates")
    if "match_requests" in existing_tables:
        op.drop_table("match_requests")
