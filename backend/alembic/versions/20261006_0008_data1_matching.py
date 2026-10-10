"""Add matching/pair extensions while retaining the existing peer-match identity."""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0008"
down_revision = "20261006_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "pairs" not in existing:
        op.create_table(
            "pairs", sa.Column("id", sa.Integer(), sa.ForeignKey("peer_matches.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("user_a", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_b", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("match_level", sa.String(32), nullable=False), sa.Column("match_reason", sa.Text(), nullable=False),
            sa.Column("match_result", sa.JSON(), nullable=False), sa.Column("reranking", sa.JSON(), nullable=False),
            sa.Column("source", sa.String(16), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(16), nullable=False), sa.Column("ended_at", sa.DateTime(timezone=True)),
            sa.Column("streak", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint("user_a", "user_b"), sa.CheckConstraint("user_a < user_b"),
            sa.CheckConstraint("match_level IN ('same_outcome','concept_overlap','complementary','shared_commitment')"),
            sa.CheckConstraint("source IN ('automatic','invitation')"),
            sa.CheckConstraint("status IN ('active','ended')"), sa.CheckConstraint("streak >= 0"))
    if "pair_memberships" not in existing:
        op.create_table(
            "pair_memberships",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("pair_id", sa.Integer(), sa.ForeignKey("pairs.id", ondelete="CASCADE"), nullable=False))
    indices = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("pair_memberships")}
    if "idx_pair_memberships_pair" not in indices:
        op.create_index("idx_pair_memberships_pair", "pair_memberships", ["pair_id"])
    if "pair_invitations" not in existing:
        op.create_table(
            "pair_invitations", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("pair_id", sa.Integer(), sa.ForeignKey("pairs.id")),
            sa.CheckConstraint("status IN ('pending','used','revoked')"),
            sa.CheckConstraint("target_user_id IS NULL OR target_user_id != owner_user_id"))
    if "pair_match_queue" not in existing:
        op.create_table(
            "pair_match_queue",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("waiting_since", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.CheckConstraint("status IN ('waiting','paired','cancelled')"))


def downgrade() -> None:
    for name in ("pair_match_queue", "pair_invitations", "pair_memberships", "pairs"):
        op.drop_table(name)
