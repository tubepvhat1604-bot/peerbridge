"""Cho coach của Data 2 đọc số đo của Data 1 và gửi lời nhắc qua chuông thông báo trong app."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..agents.plan_coach.contract import MetricSnapshot
from ..db import database
from ..home import notifications
from ..metrics.repository import MetricsRepository
from ..metrics.time import study_date
from .measurement import finalized_checkins, plan_workload

log = logging.getLogger("loop.coach")

ACTION_TITLE = {
    "reminder": "Coach: nhắc bạn check-in",
    "replan": "Coach: gợi ý giảm tải kế hoạch",
    "pair_replan": "Coach: cả hai đang chậm nhịp",
    "offer_support": "Coach: nhờ bạn cặp hỗ trợ",
}


class Data1MetricsAdapter:
    """Đổi số đo mới nhất của Data 1 (`pair_metrics_daily`) sang `MetricSnapshot` mà coach cần."""

    def load(self, pair_id: int) -> MetricSnapshot | None:
        with database() as db:
            repo = MetricsRepository(db)
            if repo.pair_row(pair_id) is None:
                return None
            metrics = repo.latest(repo.context(pair_id))
        if metrics is None:
            return None
        members = (metrics.learner_a.user_id, metrics.learner_b.user_id)
        items, versions = plan_workload(pair_id, members, metrics.computed_at)
        if set(versions) != set(members):
            return None
        today = study_date(datetime.now(UTC))
        due = {m: sum(1 for i in items if i.user_id == m and i.due_date <= today) for m in members}
        learners = {metrics.learner_a.user_id: metrics.learner_a, metrics.learner_b.user_id: metrics.learner_b}
        pacing = {m: (min(1.0, learners[m].pacing) if due[m] and learners[m].has_due_workload else None) for m in members}
        due = {m: (due[m] if pacing[m] is not None else 0) for m in members}
        last: dict[int, datetime | None] = {m: None for m in members}
        for c in finalized_checkins(pair_id, members):
            if c.status == "done" and c.finalized_at and (last[c.user_id] is None or c.finalized_at > last[c.user_id]):
                last[c.user_id] = c.finalized_at
        return MetricSnapshot(
            pair_id=pair_id, as_of=metrics.computed_at, source=metrics.metric_version,
            plan_versions=versions, pacing=pacing, due_count=due, last_checkin=last,
            gap=min(1.0, metrics.gap) if metrics.gap is not None else None, lagging_user_id=metrics.lagging_member,
        )


class InAppNotification:
    """Kênh gửi của coach: ghi thông báo trong app (chuông + Tổng quan). Ghi được thì tính là đã gửi."""

    def __init__(self, action_by_key: dict[str, str] | None = None):
        self.action_by_key = action_by_key or {}

    def send(self, user_id: int, text: str, idempotency_key: str) -> str:
        with database() as db:
            row = db.execute("SELECT action FROM pb_interventions WHERE id=?", (idempotency_key,)).fetchone()
        title = ACTION_TITLE.get(row["action"] if row else "", "Coach PeerBridge")
        return "SENT" if notifications.add(user_id, "plan", title, text, "plan") else "FAILED"


def get_team_coach_service():
    """Thay `get_coach_service` của Data 2: dùng số đo thật + thông báo trong app (+ AI viết lời nhắc nếu bật)."""
    from ..services.coach import CoachService
    from ..services.plans import PlanService

    service = CoachService(plans=PlanService(), metrics=Data1MetricsAdapter(), notification=InAppNotification())
    if service.plans.settings.coach_v2_enabled and _ai_budget_left():
        from ..agents.plan_coach.graph import make_selector

        try:
            service.selector = make_selector(service.plans.settings)
        except ValueError:
            service.selector = None
    return service


def _ai_budget_left() -> bool:
    try:
        from ..checkin.stats import budget_left_usd

        return budget_left_usd() > 0
    except Exception:
        return True
