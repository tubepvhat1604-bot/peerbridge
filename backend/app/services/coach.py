import asyncio
import json
from pathlib import Path
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..agents.plan_coach.coach import TEMPLATES, allowed_actions, decide_v1
from ..agents.plan_coach.contract import MetricSnapshot, ReplanRequest
from ..agents.plan_coach.nudge import validate_message
from ..agents.plan_coach.tracing import export_db_trace
from ..agents.plan_coach.variants import assigned_variant
from ..db import database
from ..repositories.plans import PlanError, PlanRepository, encode
from .plans import PlanService


class MetricsAdapter(Protocol):
    def load(self, pair_id: int) -> MetricSnapshot | None: ...


class TeamMetricsAdapter:
    """Optional snapshot exported by AI Data 1. Does not derive or manufacture metrics."""

    def __init__(self, path=None):
        self.path = path

    def load(self, pair_id):
        if not self.path:
            return None
        try:
            data = json.loads(Path(self.path).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            snapshot = data.get(str(pair_id))
            return MetricSnapshot.model_validate(snapshot) if snapshot else None
        except (OSError, ValueError):
            return None


class FakeMetricsAdapter:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def load(self, pair_id):
        return self.snapshot


class NotificationAdapter(Protocol):
    def send(self, user_id: int, text: str, idempotency_key: str) -> str:
        """SENT requires provider confirmation; PENDING is accepted but unconfirmed.

        Other outcomes: FAILED, NOT_CONFIGURED, SIMULATED. SE/PO owns real delivery
        and must honor local quiet hours when completing queued delivery.
        """
        ...


class UnavailableNotification:
    def send(self, user_id, text, idempotency_key):
        return "NOT_CONFIGURED"


class FakeNotification:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def send(self, user_id, text, idempotency_key):
        self.calls.append((user_id, text, idempotency_key))
        return "FAILED" if self.fail else "SIMULATED"


class CoachService:
    def __init__(self, plans=None, metrics=None, notification=None, selector=None):
        self.plans = plans or PlanService()
        self.metrics = metrics or TeamMetricsAdapter(self.plans.settings.metrics_path)
        self.notification = notification or UnavailableNotification()
        self.selector = selector

    def list(self, pair_id, user):
        with database() as db:
            PlanRepository(db).pair(pair_id, user)
            rows = db.execute(
                "SELECT * FROM pb_interventions WHERE pair_id=? AND user_id=? ORDER BY created_at DESC LIMIT 30",
                (pair_id, user["id"]),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "action": r["action"],
                    "variant": r["variant"],
                    "decision": json.loads(r["decision"]),
                    "delivery_status": r["delivery_status"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    async def evaluate(self, pair_id, user):
        decision = await self._evaluate(pair_id, user)
        body = {
            "mode": "v1",
            "provider_mode": "template",
            "prompt_version": "plan-coach-v1",
            "model": "coach-template-v1",
            **decision.get("selection", {}),
            "action": decision["action"],
        }
        decision["external_trace"] = await asyncio.to_thread(
            export_db_trace,
            self.plans.settings,
            "coach",
            body,
            decision["trace_id"],
            {
                "intervention_id": decision.get("id"),
                "proposal_id": decision.get("proposal_id"),
                "plan_version": decision.get("plan_version"),
            },
        )
        return decision

    def _record_trace(self, repo, pair_id, decision, now):
        decision["trace_id"] = repo.trace(pair_id, "coach", decision, now)

    async def _evaluate(self, pair_id, user):
        now, uid = self.plans.clock(), user["id"]
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            repo = PlanRepository(db)
            pair = repo.pair(pair_id, user)
            # Pair assignment survives missing providers and no-action evaluations.
            # Existing assignments are preserved when the feature flag changes.
            variant = assigned_variant(db, pair_id, self.plans.settings.variant_seed)
            audit = {
                "user_id": uid,
                "variant": variant,
                "evaluated_at": now.isoformat(),
                "coach_v2_enabled": self.plans.settings.coach_v2_enabled,
                "delivery_status": "NOT_APPLICABLE",
            }
            rows = {i: repo.active(pair_id, i) for i in (pair["user_a_id"], pair["user_b_id"])}
            if not all(rows.values()):
                decision = {**audit, "action": "no_action", "reason": "PLAN_UNAVAILABLE", "sent": False}
                self._record_trace(repo, pair_id, decision, now)
                return decision
            plans = {i: repo.hydrated(row) for i, row in rows.items()}
            ctx, _ = repo.context(rows[uid])
            # Current companion's declared strengths come from its own plan context.
            partner_uid = next(i for i in rows if i != uid)
            partner_ctx, _ = repo.context(rows[partner_uid])
            ctx.members = [
                m if m.user_id == uid else next(p for p in partner_ctx.members if p.user_id == partner_uid)
                for m in ctx.members
            ]
        metric_adapter_error = None
        try:
            raw = await asyncio.to_thread(self.metrics.load, pair_id)
            snapshot = (
                MetricSnapshot.model_validate(raw.model_dump() if isinstance(raw, MetricSnapshot) else raw)
                if raw is not None
                else None
            )
        except Exception as error:
            snapshot = None
            metric_adapter_error = type(error).__name__
        reason, actions, concept = allowed_actions(ctx, plans, snapshot, uid, now)
        if actions == ["no_action"]:
            decision = {**audit, "action": "no_action", "reason": reason, "sent": False}
            if metric_adapter_error:
                decision["metric_adapter_error"] = metric_adapter_error
            with database() as db:
                self._record_trace(PlanRepository(db), pair_id, decision, now)
            return decision
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            member_timezone = next(m.timezone for m in ctx.members if m.user_id == uid)
            stamp = now.astimezone(ZoneInfo(member_timezone)).date().isoformat()
            if db.execute("SELECT 1 FROM pb_interventions WHERE user_id=? AND local_date=?", (uid, stamp)).fetchone():
                decision = {**audit, "action": "no_action", "reason": "DAILY_LIMIT", "sent": False}
                self._record_trace(PlanRepository(db), pair_id, decision, now)
                return decision
        selection_trace = {"mode": "v1", "action": decide_v1(actions)}
        ai_text = None
        if variant == "ai" and self.plans.settings.coach_v2_enabled:
            try:
                if self.selector is None:
                    raise ValueError("selector_unavailable")
                selected = await asyncio.wait_for(
                    self.selector.select(actions, reason, concept), self.plans.settings.llm_timeout_seconds + 1
                )
                if not isinstance(selected, dict) or selected.get("action") not in actions:
                    raise ValueError("invalid_selector_result")
                if selected.get("mode") not in ("v2", "v1_fallback"):
                    raise ValueError("invalid_selector_mode")
                if selected["mode"] == "v2":
                    ai_text = validate_message(selected["action"], selected.get("text", ""), concept)
                selection_trace = {
                    k: v
                    for k, v in selected.items()
                    if k
                    in {
                        "action",
                        "mode",
                        "nodes",
                        "error",
                        "model",
                        "provider_mode",
                        "prompt_version",
                        "latency_ms",
                        "usage",
                        "cost",
                        "message_source",
                    }
                }
            except Exception as error:
                selection_trace = {"mode": "v1_fallback", "action": decide_v1(actions), "error": type(error).__name__}
        action = selection_trace["action"]
        if action not in actions:
            action = decide_v1(actions)
            selection_trace = {"mode": "v1_fallback", "reason": "UNAUTHORIZED_ACTION", "action": action}
        decision = {
            **audit,
            "action": action,
            "reason": reason,
            "concept_id": concept if action == "offer_support" else None,
            "allowed_actions": actions,
            "metric_source": snapshot.source,
            "metrics_as_of": snapshot.as_of.isoformat(),
            "selection": selection_trace,
            "sent": False,
            "proposal_id": None,
            "plan_version": plans[uid].plan_version,
        }
        if action == "no_action":
            with database() as db:
                self._record_trace(PlanRepository(db), pair_id, decision, now)
            return decision
        reservation_time = self.plans.clock()
        # Selection/adapter work can cross a local day boundary. Quota belongs to
        # the day on which the intervention is actually prepared for delivery.
        stamp = reservation_time.astimezone(ZoneInfo(member_timezone)).date().isoformat()
        intervention_id = str(uuid4())
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            inserted = db.execute(
                "INSERT OR IGNORE INTO pb_interventions(id,pair_id,user_id,local_date,action,variant,decision,delivery_status,created_at) VALUES (?,?,?,?,?,?,?,'RESERVED',?)",
                (intervention_id, pair_id, uid, stamp, action, variant, encode(decision), reservation_time.isoformat()),
            ).rowcount
            if not inserted:
                decision = {**audit, "action": "no_action", "reason": "DAILY_LIMIT", "sent": False}
                self._record_trace(PlanRepository(db), pair_id, decision, reservation_time)
                return decision
        # Reservation committed before any adapter call. Crashes cannot cause another daily send.
        if action in ("replan", "pair_replan"):
            try:
                proposal = self.plans.replan(
                    pair_id, user, ReplanRequest(expected_version=plans[uid].plan_version, reason=TEMPLATES[action])
                )
                decision["proposal_id"] = proposal["id"]
            except (PlanError, ValueError):
                decision["preparation_error"] = "REPLAN_UNAVAILABLE_REFRESH_PLAN"
        text = ai_text or TEMPLATES[action].format(concept_id=concept or "")
        decision["message_source"] = "ai" if ai_text else "template"
        if decision.get("preparation_error"):
            text = "Chưa tạo được phương án giảm tải. Bạn hãy mở Plan để kiểm tra lại tiến độ, mục tiêu và thời gian."
            decision["message_source"] = "template"
        try:
            delivery_time = self.plans.clock().astimezone(ZoneInfo(member_timezone))
            if delivery_time.hour >= 22 or delivery_time.hour < 7:
                status = "SUPPRESSED_QUIET_HOURS"
            else:
                status = await asyncio.to_thread(self.notification.send, uid, text, intervention_id)
            if status not in ("SENT", "PENDING", "SIMULATED", "FAILED", "NOT_CONFIGURED"):
                status = "SUPPRESSED_QUIET_HOURS" if status == "SUPPRESSED_QUIET_HOURS" else "FAILED"
        except Exception:
            status = "FAILED"
        decision.update(
            {
                "id": intervention_id,
                "variant": variant,
                "text": text,
                "sent": status == "SENT",
                "delivery_status": status,
            }
        )
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE pb_interventions SET decision=?,delivery_status=? WHERE id=?",
                (encode(decision), status, intervention_id),
            )
            db.execute(
                "INSERT INTO pb_delivery_attempts(intervention_id,status,created_at) VALUES (?,?,?)",
                (intervention_id, status, self.plans.clock().isoformat()),
            )
            self._record_trace(PlanRepository(db), pair_id, decision, now)
        return decision


def get_coach_service():
    service = CoachService()
    if service.plans.settings.coach_v2_enabled:
        from ..agents.plan_coach.graph import make_selector

        try:
            service.selector = make_selector(service.plans.settings)
        except ValueError:
            # Invalid provider configuration keeps the same code rules and limits.
            service.selector = None
    return service
