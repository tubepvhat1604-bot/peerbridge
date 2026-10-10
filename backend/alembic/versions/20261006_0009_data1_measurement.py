"""Add daily measurement snapshots; preserve prior Data 1 and teammate schemas."""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0009"
down_revision = "20261006_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "pair_metrics_daily" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "pair_metrics_daily",
            sa.Column("pair_id", sa.Integer(), sa.ForeignKey("pairs.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("date", sa.Date(), primary_key=True),
            *[sa.Column(name, sa.Float(), nullable=False) for name in ("pacing_a", "pacing_b", "pair_score", "gap")],
            sa.Column("risk_a", sa.Float()), sa.Column("risk_b", sa.Float()),
            sa.Column("streak", sa.Integer(), nullable=False),
            sa.Column("metric_version", sa.String(64), nullable=False),
            sa.Column("pair_started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            *[sa.CheckConstraint(f"{name} >= 0") for name in ("pacing_a", "pacing_b", "pair_score", "gap", "streak")],
            sa.CheckConstraint("risk_a BETWEEN 0 AND 1"), sa.CheckConstraint("risk_b BETWEEN 0 AND 1"),
            sa.CheckConstraint("pair_score = min(pacing_a,pacing_b)"), sa.CheckConstraint("gap = abs(pacing_a-pacing_b)"))
    indices = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("pair_metrics_daily")}
    if "idx_pair_metrics_date" not in indices:
        op.create_index("idx_pair_metrics_date", "pair_metrics_daily", ["date", "pair_id"])


def downgrade() -> None:
    op.drop_table("pair_metrics_daily")
