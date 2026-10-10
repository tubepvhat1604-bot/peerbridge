"""Add Data 1 concepts and onboarding without changing legacy profile or matching tables."""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0007"
down_revision = "20261003_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "concepts" not in existing:
        op.create_table(
            "concepts",
            sa.Column("id", sa.String(120), primary_key=True),
            sa.Column("domain", sa.String(16), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("prerequisites", sa.JSON(), nullable=False),
            sa.Column("aliases", sa.JSON(), nullable=False),
            sa.Column("embedding", sa.JSON()),
            sa.Column("catalog_version", sa.String(40), nullable=False),
            sa.CheckConstraint("domain IN ('sql', 'python')", name="ck_concepts_domain"),
        )
    if "onboarding_profiles" not in existing:
        op.create_table(
            "onboarding_profiles",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("mappings", sa.JSON(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(timezone=True)),
            sa.CheckConstraint("revision >= 1", name="ck_onboarding_revision"),
            sa.CheckConstraint("status IN ('draft', 'confirmed')", name="ck_onboarding_status"),
        )
    if "user_concepts" not in existing:
        op.create_table(
            "user_concepts",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("concept_id", sa.String(120), sa.ForeignKey("concepts.id"), primary_key=True),
            sa.Column("role", sa.String(16), primary_key=True),
            sa.Column("self_level", sa.String(16), nullable=False),
            sa.Column("theta", sa.Float(), nullable=False),
            sa.Column("n_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.CheckConstraint("role IN ('need', 'offer')", name="ck_user_concepts_role"),
            sa.CheckConstraint("self_level IN ('unknown', 'learning', 'strong')", name="ck_user_concepts_level"),
            sa.CheckConstraint("n_attempts >= 0", name="ck_user_concepts_attempts"),
        )
    indices = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("user_concepts")}
    if "idx_user_concepts_concept" not in indices:
        op.create_index("idx_user_concepts_concept", "user_concepts", ["concept_id", "role"])


def downgrade() -> None:
    # Used only when an operator explicitly requests rollback; not invoked by app startup.
    for name in ("user_concepts", "onboarding_profiles", "concepts"):
        op.drop_table(name)
