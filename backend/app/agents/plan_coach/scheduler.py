import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .contract import Issue, ItemStatus, Member, PersonalPlan, PlanItem, PlannerInput, PlannerOutput, Task


class PlanValidationError(ValueError):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("; ".join(i.code + ": " + i.message for i in issues))


def concept_order(ctx: PlannerInput, member: Member) -> list[str]:
    catalog = {c.id: c for c in ctx.concepts}
    seen, result = set(member.known_concept_ids), []

    def visit(cid):
        if cid in seen:
            return
        seen.add(cid)
        for prerequisite in catalog[cid].prerequisites:
            visit(prerequisite)
        result.append(cid)

    for cid in member.concept_ids:
        visit(cid)
    return result


def validate_context(ctx: PlannerInput, user_ids=None):
    if user_ids is not None and (not user_ids or not user_ids <= {m.user_id for m in ctx.members}):
        raise PlanValidationError([Issue(code="MEMBER_SCOPE", message="Selected members must belong to the pair")])
    catalog = {c.id: c for c in ctx.concepts}
    issues = []
    if len(catalog) != len(ctx.concepts):
        issues.append(Issue(code="DUPLICATE_CONCEPT", message="Concept IDs must be unique"))
    for concept in ctx.concepts:
        for prerequisite in concept.prerequisites:
            if prerequisite not in catalog:
                issues.append(
                    Issue(
                        code="UNKNOWN_PREREQUISITE",
                        message=f"Missing prerequisite {prerequisite}",
                        concept_id=concept.id,
                    )
                )
        if any(r not in ctx.resources for r in concept.resource_ids):
            issues.append(
                Issue(
                    code="UNKNOWN_RESOURCE", message="Resource is not in the supplied registry", concept_id=concept.id
                )
            )
    for m in ctx.members:
        for cid in m.concept_ids + m.known_concept_ids + m.can_help_concept_ids:
            if cid not in catalog:
                issues.append(
                    Issue(code="UNKNOWN_CONCEPT", message=f"Unknown concept {cid}", user_id=m.user_id, concept_id=cid)
                )
        if (user_ids is None or m.user_id in user_ids) and m.deadline and m.deadline <= ctx.planning_start:
            issues.append(
                Issue(code="DEADLINE_PAST", message="Deadline is before the planning start", user_id=m.user_id)
            )
    if issues:
        raise PlanValidationError(issues)
    visited, visiting = set(), set()

    def visit(cid):
        if cid in visiting:
            raise PlanValidationError(
                [Issue(code="PREREQUISITE_CYCLE", message=f"Cycle through {cid}", concept_id=cid)]
            )
        if cid in visited:
            return
        visiting.add(cid)
        for prerequisite in catalog[cid].prerequisites:
            visit(prerequisite)
        visiting.remove(cid)
        visited.add(cid)

    for cid in catalog:
        visit(cid)


def validate_tasks(ctx: PlannerInput, tasks: list[Task], completed: list[PlanItem] | None = None, *, user_ids=None):
    validate_context(ctx, user_ids)
    catalog = {c.id: c for c in ctx.concepts}
    members = {m.user_id: m for m in ctx.members}
    done = {(i.user_id, i.concept_id) for i in completed or []}
    expected = {
        (m.user_id, cid)
        for m in ctx.members
        if user_ids is None or m.user_id in user_ids
        for cid in concept_order(ctx, m)
    } - done
    actual, issues = set(), []
    for task in tasks:
        key = task.user_id, task.concept_id
        if key in actual:
            issues.append(
                Issue(
                    code="DUPLICATE_TASK",
                    message="One task per required concept in MVP",
                    user_id=task.user_id,
                    concept_id=task.concept_id,
                )
            )
        actual.add(key)
        if task.user_id not in members or task.concept_id not in catalog or key not in expected:
            issues.append(
                Issue(
                    code="UNEXPECTED_TASK",
                    message="Task is outside the authorized goal/concept closure",
                    user_id=task.user_id,
                    concept_id=task.concept_id,
                )
            )
        if any(r not in ctx.resources for r in task.resource_ids):
            issues.append(
                Issue(
                    code="UNKNOWN_RESOURCE",
                    message="Only supplied resource IDs are allowed",
                    concept_id=task.concept_id,
                )
            )
        if re.search(
            r"https?://|www\.|\b[a-z0-9-]+\.(?:com|org|net|edu|io|vn)(?:/|\b)",
            task.action + " " + task.expected_output,
            re.I,
        ):
            issues.append(
                Issue(code="INLINE_URL", message="Use resource IDs, not generated URLs", concept_id=task.concept_id)
            )
    for uid, cid in expected - actual:
        issues.append(
            Issue(
                code="MISSING_TASK",
                message="Required concept/prerequisite task is missing",
                user_id=uid,
                concept_id=cid,
            )
        )
    if issues:
        raise PlanValidationError(issues)


def template_tasks(ctx: PlannerInput, completed: list[PlanItem] | None = None) -> list[Task]:
    validate_context(ctx)
    catalog = {c.id: c for c in ctx.concepts}
    done = {(i.user_id, i.concept_id) for i in completed or []}
    return [
        Task(
            user_id=m.user_id,
            concept_id=cid,
            action=catalog[cid].action,
            expected_output=catalog[cid].expected_output,
            est_minutes=catalog[cid].est_minutes,
            resource_ids=catalog[cid].resource_ids,
        )
        for m in ctx.members
        for cid in concept_order(ctx, m)
        if (m.user_id, cid) not in done
    ]


def week_key(stamp: datetime, member: Member) -> str:
    local = stamp.astimezone(ZoneInfo(member.timezone)).date()
    return (local - timedelta(days=local.weekday())).isoformat()


def slots(ctx: PlannerInput, member: Member):
    tz = ZoneInfo(member.timezone)
    begin = ctx.planning_start.astimezone(tz).date()
    limit = ctx.planning_start + timedelta(days=ctx.horizon_days)
    result = []
    for offset in range(ctx.horizon_days + 1):
        day = begin + timedelta(days=offset)
        for window in member.availability:
            if day.weekday() != window.day_of_week:
                continue
            start = datetime.combine(day, window.start_time, tz).astimezone(UTC)
            end = datetime.combine(day, window.end_time, tz).astimezone(UTC)
            # Reject nonexistent/ambiguous DST wall times rather than guessing a fold.
            for wall, instant in [(window.start_time, start), (window.end_time, end)]:
                local = datetime.combine(day, wall, tz)
                if (
                    instant.astimezone(tz).replace(tzinfo=None) != local.replace(tzinfo=None)
                    or local.utcoffset() != local.replace(fold=1).utcoffset()
                ):
                    raise PlanValidationError(
                        [
                            Issue(
                                code="DST_WINDOW",
                                message="Ambiguous or nonexistent local window",
                                user_id=member.user_id,
                            )
                        ]
                    )
            end = min(end, limit, member.deadline or limit)
            if end > ctx.planning_start and start < limit:
                result.append((f"{window.id}@{day.isoformat()}", max(start, ctx.planning_start), end))
    return sorted(result, key=lambda s: (s[1], s[0]))


def if_then(item: PlanItem, member: Member) -> str:
    local = item.scheduled_start.astimezone(ZoneInfo(member.timezone))
    return f"Nếu {local:%d/%m/%Y lúc %H:%M} tại {member.location} thì {item.action} ({item.est_minutes} phút)."


def schedule(
    ctx: PlannerInput,
    tasks: list[Task],
    *,
    completed: list[PlanItem] | None = None,
    previous: list[PlanItem] | None = None,
    budget_caps: dict[tuple[int, str], int] | None = None,
    user_ids: set[int] | None = None,
) -> PlannerOutput:
    completed = completed or []
    validate_tasks(ctx, tasks, completed, user_ids=user_ids)
    catalog = {c.id: c for c in ctx.concepts}
    task_map = {(t.user_id, t.concept_id): t for t in tasks}
    prior = {(i.user_id, i.concept_id): i for i in previous or []}
    plans = []
    for m in ctx.members:
        if user_ids is not None and m.user_id not in user_ids:
            continue
        items = [i.model_copy(update={"plan_version": ctx.plan_version}) for i in completed if i.user_id == m.user_id]
        ends = {i.concept_id: i.scheduled_end for i in items}
        used_slots = {i.slot_id for i in items}
        spent = defaultdict(int)
        for i in items:
            spent[week_key(i.scheduled_start, m)] += i.est_minutes
        new_spent = defaultdict(int)
        deferred = []
        windows = slots(ctx, m)
        for cid in concept_order(ctx, m):
            if cid in ends:
                continue
            task = task_map[(m.user_id, cid)]
            previous_item = prior.get((m.user_id, cid))
            item = PlanItem(
                **task.model_dump(),
                pair_id=ctx.pair_id,
                plan_version=ctx.plan_version,
                status=ItemStatus.DEFERRED,
                **({"id": previous_item.id} if previous_item else {}),
            )
            missing = [p for p in catalog[cid].prerequisites if p not in m.known_concept_ids and p not in ends]
            reason = "PREREQUISITE_DEFERRED" if missing else "NO_FITTING_SLOT_OR_BUDGET"
            if not missing:
                for slot_id, start, end in windows:
                    if slot_id in used_slots:
                        continue
                    prerequisites_end = [ends[p] for p in catalog[cid].prerequisites if p in ends]
                    start = max([start] + prerequisites_end)
                    for busy in sorted(ctx.busy_intervals.get(m.user_id, []), key=lambda b: b.start):
                        if start < busy.end and busy.start < start + timedelta(minutes=task.est_minutes):
                            start = busy.end.astimezone(UTC)
                    finish = start + timedelta(minutes=task.est_minutes)
                    if finish > end:
                        continue
                    wk = week_key(start, m)
                    if spent[wk] + task.est_minutes > m.committed_minutes_per_week * 4 // 5:
                        continue
                    if budget_caps is not None and new_spent[wk] + task.est_minutes > budget_caps.get(
                        (m.user_id, wk), m.committed_minutes_per_week * 4 // 5
                    ):
                        continue
                    if any(start < i.scheduled_end and i.scheduled_start < finish for i in items):
                        continue
                    item = item.model_copy(
                        update={
                            "status": ItemStatus.SCHEDULED,
                            "scheduled_start": start,
                            "scheduled_end": finish,
                            "slot_id": slot_id,
                        }
                    )
                    item.if_then_text = if_then(item, m)
                    used_slots.add(slot_id)
                    spent[wk] += task.est_minutes
                    new_spent[wk] += task.est_minutes
                    ends[cid] = finish
                    items.append(item)
                    break
            if item.status == ItemStatus.DEFERRED:
                item.defer_reason = reason
                deferred.append(item)
        warnings = (
            [
                Issue(
                    code="PARTIAL_PLAN",
                    message="Một phần mục tiêu chưa được xếp trong khoảng lập kế hoạch; xem mục để sau.",
                    user_id=m.user_id,
                )
            ]
            if deferred
            else []
        )
        if not any(i.status == ItemStatus.SCHEDULED for i in items) and deferred:
            warnings.append(
                Issue(
                    code="NO_FEASIBLE_SCHEDULE",
                    message="Không có khung/ngân sách đủ cho việc 30–90 phút và tiên quyết.",
                    user_id=m.user_id,
                )
            )
        plans.append(
            PersonalPlan(
                user_id=m.user_id,
                pair_id=ctx.pair_id,
                plan_version=ctx.plan_version,
                items=items,
                deferred_items=deferred,
                partial=bool(deferred),
                warnings=warnings,
            )
        )
    result = PlannerOutput(pair_id=ctx.pair_id, plans=plans)
    validate_plan(ctx, result, budget_caps=budget_caps, user_ids=user_ids)
    return result


def validate_plan(ctx: PlannerInput, output: PlannerOutput, *, budget_caps=None, user_ids=None):
    validate_context(ctx, user_ids)
    issues, ids = [], set()
    catalog = {c.id: c for c in ctx.concepts}
    members = {m.user_id: m for m in ctx.members if user_ids is None or m.user_id in user_ids}
    if (
        output.pair_id != ctx.pair_id
        or {p.user_id for p in output.plans} != set(members)
        or len(output.plans) != len(members)
    ):
        raise PlanValidationError(
            [Issue(code="PAIR_SCOPE", message="Output must contain exactly the two authorized members")]
        )
    for plan in output.plans:
        m = members[plan.user_id]
        if plan.pair_id != ctx.pair_id or plan.plan_version != ctx.plan_version:
            issues.append(
                Issue(code="PLAN_SCOPE", message="Personal plan pair/version must match context", user_id=m.user_id)
            )
        windows = {key: (start, end) for key, start, end in slots(ctx, m)}
        spent, new_spent, slot_ids = defaultdict(int), defaultdict(int), set()
        all_items = plan.items + plan.deferred_items
        expected = set(concept_order(ctx, m))
        actual = {i.concept_id for i in all_items}
        if actual != expected or len(actual) != len(all_items):
            issues.append(
                Issue(
                    code="CONCEPT_COVERAGE",
                    message="Required concepts must appear exactly once, including deferred prerequisites",
                    user_id=m.user_id,
                )
            )
        ends = {i.concept_id: i.scheduled_end for i in plan.items}
        for i in all_items:

            def fail(code, message):
                issues.append(
                    Issue(code=code, message=message, user_id=m.user_id, concept_id=i.concept_id, item_id=i.id)
                )

            if i.id in ids or i.user_id != m.user_id or i.pair_id != ctx.pair_id or i.plan_version != ctx.plan_version:
                fail("ITEM_SCOPE", "Duplicate ID or incorrect owner/pair/version")
            ids.add(i.id)
            if not 30 <= i.est_minutes <= 90:
                fail("TASK_DURATION", "Task must take 30–90 minutes")
            if any(r not in ctx.resources for r in i.resource_ids):
                fail("UNKNOWN_RESOURCE", "Only supplied learning resources are allowed")
            if i.status == ItemStatus.COMPLETED and not i.completed_at:
                fail("COMPLETION_REQUIRED", "Completed items require confirmation timestamp")
            if i.concept_id not in catalog:
                fail("UNKNOWN_CONCEPT", "Unknown concept")
                continue
            if i.status == ItemStatus.DEFERRED:
                if (
                    i not in plan.deferred_items
                    or i.scheduled_start
                    or i.scheduled_end
                    or i.if_then_text
                    or not i.defer_reason
                ):
                    fail("DEFERRED_STATE", "Deferred work needs a reason and no fabricated schedule")
                continue
            if i not in plan.items or not i.scheduled_start or not i.scheduled_end:
                fail("SCHEDULE_REQUIRED", "Scheduled/completed work requires timestamps")
                continue
            if i.scheduled_start.tzinfo is None or i.scheduled_end.tzinfo is None:
                fail("TIMEZONE_REQUIRED", "Schedule must be timezone-aware")
                continue
            if (i.scheduled_end - i.scheduled_start).total_seconds() != i.est_minutes * 60:
                fail("DURATION", "Schedule duration differs from est_minutes")
            wk = week_key(i.scheduled_start, m)
            spent[wk] += i.est_minutes
            if i.slot_id in slot_ids:
                fail("SLOT_REUSED", "At most one activity per window occurrence")
            slot_ids.add(i.slot_id)
            if i.status != ItemStatus.COMPLETED:
                if any(
                    i.scheduled_start < b.end and b.start < i.scheduled_end
                    for b in ctx.busy_intervals.get(m.user_id, [])
                ):
                    fail("BUSY_OVERLAP", "Activity overlaps an existing scheduled study session")
                new_spent[wk] += i.est_minutes
                window = windows.get(i.slot_id)
                if not window or not (window[0] <= i.scheduled_start < i.scheduled_end <= window[1]):
                    fail("OUTSIDE_WINDOW", "Work must fit one remaining availability window and deadline")
                if i.scheduled_start < ctx.planning_start:
                    fail("PAST_SCHEDULE", "Cannot schedule work in the past")
                if i.if_then_text != if_then(i, m):
                    fail("IF_THEN_MISMATCH", "If-then text must use the actual schedule and task")
                for prerequisite in catalog[i.concept_id].prerequisites:
                    if prerequisite not in m.known_concept_ids and (
                        prerequisite not in ends or ends[prerequisite] > i.scheduled_start
                    ):
                        fail("PREREQUISITE_ORDER", f"{prerequisite} must finish before {i.concept_id}")
        for left_index, left in enumerate(plan.items):
            for right in plan.items[left_index + 1 :]:
                if (
                    left.scheduled_start
                    and right.scheduled_start
                    and left.scheduled_end
                    and right.scheduled_end
                    and left.scheduled_start < right.scheduled_end
                    and right.scheduled_start < left.scheduled_end
                ):
                    issues.append(
                        Issue(code="OVERLAP", message="A member has overlapping activities", user_id=m.user_id)
                    )
        if any(minutes > m.committed_minutes_per_week * 4 // 5 for minutes in spent.values()):
            issues.append(
                Issue(code="WEEKLY_BUDGET", message="Weekly 80% commitment budget exceeded", user_id=m.user_id)
            )
        if budget_caps and any(
            minutes > budget_caps.get((m.user_id, wk), m.committed_minutes_per_week * 4 // 5)
            for wk, minutes in new_spent.items()
        ):
            issues.append(Issue(code="REPLAN_BUDGET", message="Remaining reduced budget exceeded", user_id=m.user_id))
        if plan.partial != bool(plan.deferred_items):
            issues.append(Issue(code="PARTIAL_FLAG", message="Partial plans must be labelled", user_id=m.user_id))
    if issues:
        raise PlanValidationError(issues)
