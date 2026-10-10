"""Code decides permissible actions from AI Data 1 metrics, never private chat."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from .scheduler import concept_order

TEMPLATES = {
    "reminder": "Bạn đã vắng check-in hai ngày. Chọn một việc nhỏ trong Plan và check-in khi làm xong nhé.",
    "replan": "Nhịp học đang chậm hơn cam kết. Bạn có thể xem phương án giảm tải 20% và quyết định có áp dụng không.",
    "pair_replan": "Cả hai đang chậm nhịp. Mỗi người có thể xem phương án giảm tải 20% để giữ cam kết phù hợp hơn.",
    "offer_support": "Bạn có thể đề nghị bạn đồng hành hỗ trợ concept {concept_id}. Việc chia sẻ cần hai người đồng ý.",
}


def allowed_actions(ctx, plans, metrics, uid, now):
    """Returns a gate reason and code-authorized actions (always includes no_action)."""
    member = next(m for m in ctx.members if m.user_id == uid)
    local = now.astimezone(ZoneInfo(member.timezone))
    if local.hour >= 22 or local.hour < 7:
        return "QUIET_HOURS", ["no_action"], None
    if metrics is None:
        return "METRICS_UNAVAILABLE", ["no_action"], None
    ids = {m.user_id for m in ctx.members}
    if (
        metrics.pair_id != ctx.pair_id
        or now < metrics.as_of
        or now - metrics.as_of > timedelta(hours=24)
        or set(metrics.plan_versions) != ids
        or set(metrics.pacing) != ids
        or set(metrics.due_count) != ids
        or set(metrics.last_checkin) != ids
        or any(metrics.plan_versions[i] != plans[i].plan_version for i in ids)
        or any(v and v > now for v in metrics.last_checkin.values())
        or any(metrics.due_count[i] == 0 and metrics.pacing[i] is not None for i in ids)
    ):
        return "METRICS_INVALID_OR_STALE", ["no_action"], None
    if metrics.due_count[uid] == 0 or metrics.pacing[uid] is None:
        return "NO_DUE_WORK_OR_INSUFFICIENT_DATA", ["no_action"], None
    actions, support = [], None
    if all(metrics.due_count[i] > 0 and metrics.pacing[i] is not None and metrics.pacing[i] < 0.7 for i in ids):
        actions.append("pair_replan")
    elif metrics.pacing[uid] < 0.7:
        actions.append("replan")
    partner = next(m for m in ctx.members if m.user_id != uid)
    unfinished = {i.concept_id for i in plans[uid].items + plans[uid].deferred_items if i.status != "COMPLETED"}
    if metrics.gap is not None and metrics.gap > 0.3 and metrics.lagging_user_id == uid:
        support = next(
            (c for c in concept_order(ctx, member) if c in unfinished and c in partner.can_help_concept_ids), None
        )
        if support:
            actions.append("offer_support")
    last = metrics.last_checkin[uid]
    if last is None:
        due = [i.scheduled_end for i in plans[uid].items if i.scheduled_end and i.scheduled_end <= now]
        last = min(due) if due else None
    if last is not None and now - last >= timedelta(days=2):
        actions.append("reminder")
    return "ELIGIBLE" if actions else "NO_TRIGGER", actions + ["no_action"], support


def decide_v1(actions):
    return actions[0]
