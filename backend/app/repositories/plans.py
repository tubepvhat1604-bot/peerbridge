"""Persistence on db.py's runtime connection; callers own transactions."""

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from ..agents.plan_coach.contract import ItemStatus, PersonalPlan, PlanItem, PlannerInput


def encode(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class PlanError(ValueError):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class PlanRepository:
    def __init__(self, connection):
        self.db = connection

    def pair(self, pair_id, user):
        row = self.db.execute("SELECT * FROM peer_matches WHERE id=?", (pair_id,)).fetchone()
        if user.get("role") != "STUDENT" or user.get("is_seed"):
            raise PlanError("FORBIDDEN", "Chỉ sinh viên thật được dùng Plan", 403)
        if not row or user["id"] not in (row["user_a_id"], row["user_b_id"]):
            raise PlanError("PAIR_FORBIDDEN", "Bạn không thuộc cặp học này", 403)
        return dict(row)

    def active(self, pair_id, user_id):
        row = self.db.execute(
            "SELECT * FROM pb_plans WHERE pair_id=? AND user_id=? AND status='ACTIVE'", (pair_id, user_id)
        ).fetchone()
        return dict(row) if row else None

    def plan(self, plan_id, pair_id, user_id):
        row = self.db.execute(
            "SELECT * FROM pb_plans WHERE id=? AND pair_id=? AND user_id=?", (plan_id, pair_id, user_id)
        ).fetchone()
        if not row:
            raise PlanError("PLAN_NOT_FOUND", "Không tìm thấy kế hoạch", 404)
        return dict(row)

    def next_version(self, pair_id, user_id):
        return self.db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM pb_plans WHERE pair_id=? AND user_id=?", (pair_id, user_id)
        ).fetchone()[0]

    def hydrated(self, row):
        plan = PersonalPlan.model_validate_json(row["payload"])
        completed = {
            r["id"]: dict(r)
            for r in self.db.execute(
                "SELECT id,completed_at,completed_payload FROM pb_plan_items WHERE pair_id=? AND user_id=? AND completed_at IS NOT NULL",
                (row["pair_id"], row["user_id"]),
            )
        }
        items, deferred = [], []
        for item in plan.items + plan.deferred_items:
            if item.id in completed:
                record = completed[item.id]
                if record["completed_payload"]:
                    item = PlanItem.model_validate_json(record["completed_payload"])
                    item.plan_version = row["version"]
                item.status = ItemStatus.COMPLETED
                item.completed_at = datetime.fromisoformat(record["completed_at"])
            (deferred if item.status == ItemStatus.DEFERRED else items).append(item)
        plan.items, plan.deferred_items = items, deferred
        plan.partial = bool(deferred)
        if not deferred:
            plan.warnings = []
        return plan

    def progress_hash(self, row):
        plan = self.hydrated(row)
        return digest(sorted((i.id, i.completed_at.isoformat()) for i in plan.items if i.completed_at))

    def insert(self, plan, ctx, now, *, status="ACTIVE", base=None, progress=None, reason=None, caps=None):
        envelope = {
            "input": ctx.model_dump(mode="json"),
            "budget_caps": [[uid, week, minutes] for (uid, week), minutes in (caps or {}).items()],
        }
        cursor = self.db.execute(
            """INSERT INTO pb_plans(pair_id,user_id,version,status,payload,context,base_plan_id,progress_hash,cutoff,reason,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                plan.pair_id,
                plan.user_id,
                plan.plan_version,
                status,
                encode(plan),
                encode(envelope),
                base,
                progress,
                ctx.planning_start.isoformat(),
                reason,
                now.isoformat(),
            ),
        )
        for item in plan.items + plan.deferred_items:
            existing = self.db.execute(
                "SELECT pair_id,user_id,concept_id FROM pb_plan_items WHERE id=?", (item.id,)
            ).fetchone()
            if existing and tuple(existing) != (plan.pair_id, plan.user_id, item.concept_id):
                raise PlanError("ITEM_ID_COLLISION", "ID của việc đã thuộc một kế hoạch khác")
            self.db.execute(
                "INSERT OR IGNORE INTO pb_plan_items(id,pair_id,user_id,concept_id,completed_at) VALUES (?,?,?,?,?)",
                (
                    item.id,
                    plan.pair_id,
                    plan.user_id,
                    item.concept_id,
                    item.completed_at.isoformat() if item.completed_at else None,
                ),
            )
        return int(cursor.lastrowid)

    def context(self, row):
        envelope = json.loads(row["context"])
        return PlannerInput.model_validate(envelope["input"]), {(u, w): n for u, w, n in envelope["budget_caps"]}

    def trace(self, pair_id, kind, body, now):
        trace_id = str(uuid4())
        self.db.execute(
            "INSERT INTO pb_traces(id,pair_id,kind,body,created_at) VALUES (?,?,?,?,?)",
            (trace_id, pair_id, kind, encode(body), now.isoformat()),
        )
        return trace_id
