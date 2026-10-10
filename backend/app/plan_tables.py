"""Plan tables share existing SQLAlchemy metadata; runtime uses storage.SCHEMA."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, Table, Text, UniqueConstraint, text

from .database import Base

metadata = Base.metadata
plans = Table(
    "pb_plans",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("pair_id", Integer, ForeignKey("peer_matches.id"), nullable=False),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("payload", Text, nullable=False),
    Column("context", Text, nullable=False),
    Column("base_plan_id", Integer, ForeignKey("pb_plans.id")),
    Column("progress_hash", Text),
    Column("cutoff", Text),
    Column("reason", Text),
    Column("created_at", Text, nullable=False),
    Column("accepted_at", Text),
    UniqueConstraint("pair_id", "user_id", "version"),
    CheckConstraint("version > 0"),
    CheckConstraint("status IN ('DRAFT','ACTIVE','SUPERSEDED','REJECTED')"),
)
Index(
    "pb_one_active_plan",
    plans.c.pair_id,
    plans.c.user_id,
    unique=True,
    sqlite_where=text("status='ACTIVE'"),
    postgresql_where=text("status='ACTIVE'"),
)
items = Table(
    "pb_plan_items",
    metadata,
    Column("id", Text, primary_key=True),
    Column("pair_id", Integer, ForeignKey("peer_matches.id"), nullable=False),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("concept_id", Text, nullable=False),
    Column("completed_at", Text),
    Column("completed_payload", Text),
)
requests = Table(
    "pb_plan_requests",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("pair_id", Integer, ForeignKey("peer_matches.id"), nullable=False),
    Column("actor_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("request_key", Text, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("owner_token", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("result", Text),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("pair_id", "actor_id", "request_key"),
    CheckConstraint("status IN ('PENDING','DONE','FAILED')"),
)
completion = Table(
    "pb_completion_events",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column("item_id", Text, ForeignKey("pb_plan_items.id"), nullable=False),
    Column("event_hash", Text, nullable=False),
    Column("confirmed_at", Text, nullable=False),
)
interventions = Table(
    "pb_interventions",
    metadata,
    Column("id", Text, primary_key=True),
    Column("pair_id", Integer, ForeignKey("peer_matches.id"), nullable=False),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("local_date", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("variant", Text, nullable=False),
    Column("decision", Text, nullable=False),
    Column("delivery_status", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("user_id", "local_date"),
)
attempts = Table(
    "pb_delivery_attempts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("intervention_id", Text, ForeignKey("pb_interventions.id"), nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)
variants = Table(
    "pb_variants",
    metadata,
    Column("pair_id", Integer, ForeignKey("peer_matches.id"), primary_key=True),
    Column("variant", Text, nullable=False),
)
traces = Table(
    "pb_traces",
    metadata,
    Column("id", Text, primary_key=True),
    Column("pair_id", Integer, ForeignKey("peer_matches.id"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)
PLAN_TABLES = [plans, items, requests, completion, interventions, attempts, variants, traces]
