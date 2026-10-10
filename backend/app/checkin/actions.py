"""Cầu nối giữa check-in và dữ liệu của các phần khác trong app.

- Cặp học: bảng `pairs` + `pair_memberships` của Data 1 (chỉ cặp đang `active`). Chưa có thì dùng kết nối
  mới nhất trong `peer_matches` (nút "Kết nối" trên giao diện). Plan của Data 2 cũng gắn với `peer_matches.id`.
- Tên hiển thị: `profiles.display_name`.
- Concept và điểm mạnh: `concepts`, `user_concepts.theta` của Data 1.
- Mục plan đang mở: plan ACTIVE của Data 2 (`pb_plans`, đọc qua PlanRepository).
- Đánh dấu xong: gọi `PlanService.complete(CompletionEvent)` của Data 2. Vision không tự sửa bảng plan.

Muốn đổi nguồn dữ liệu nào thì chỉ sửa file này.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..agents.plan_coach.contract import CompletionEvent, ItemStatus
from ..db import database
from ..repositories.plans import PlanError, PlanRepository
from .config import get_settings
from .models import Checkin, CheckinStatus
from .notify import notify
from .schemas import ConceptRef, PlanItemRef
from .timeutil import now_utc, to_local

_IF_THEN = re.compile(r"^\s*Nếu\b.*?\bthì\s+", re.IGNORECASE | re.DOTALL)


def short_label(if_then_text: str) -> str:
    """'Nếu 19:00 thứ 3 ở thư viện thì làm 5 bài JOIN' -> 'Làm 5 bài JOIN'."""
    core = _IF_THEN.sub("", if_then_text or "").strip() or (if_then_text or "").strip()
    return core[:1].upper() + core[1:]


class PairAccessError(PermissionError):
    pass


@dataclass
class Person:
    id: int
    display_name: str


@dataclass
class PairInfo:
    pair_id: int
    user_a: int
    user_b: int
    me: Person
    partner: Person


def display_name(user_id: int) -> str:
    with database() as db:
        row = db.execute("SELECT display_name FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    return row["display_name"] if row else "Bạn học"


def get_pair_for_user(user_id: int) -> PairInfo:
    with database() as db:
        row = db.execute(
            "SELECT p.id, p.user_a, p.user_b FROM pair_memberships m JOIN pairs p ON p.id = m.pair_id "
            "WHERE m.user_id=? AND p.status='active'",
            (user_id,),
        ).fetchone()
        if row is None:  # chưa ghép cặp kiểu Data 1: dùng kết nối gần nhất
            row = db.execute(
                "SELECT id, user_a_id AS user_a, user_b_id AS user_b FROM peer_matches "
                "WHERE user_a_id=? OR user_b_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
                (user_id, user_id),
            ).fetchone()
    if row is None:
        raise PairAccessError("Bạn chưa có bạn học. Hãy kết nối với một bạn trước khi check-in.")
    partner_id = row["user_b"] if row["user_a"] == user_id else row["user_a"]
    return PairInfo(
        pair_id=row["id"],
        user_a=row["user_a"],
        user_b=row["user_b"],
        me=Person(user_id, display_name(user_id)),
        partner=Person(partner_id, display_name(partner_id)),
    )


def item_label(item) -> str:
    return short_label(item.if_then_text) if item.if_then_text else item.action


def plan_items(pair_id: int, user_id: int):
    """(plan_version, các mục đã xếp) của plan ACTIVE; (None, []) nếu chưa có plan."""
    with database() as db:
        repo = PlanRepository(db)
        row = repo.active(pair_id, user_id)
        if row is None:
            return None, []
        plan = repo.hydrated(row)
    return plan.plan_version, plan.items


def open_plan_items(pair_id: int, user_id: int, now: dt.datetime | None = None) -> tuple[int | None, list[PlanItemRef]]:
    """Các mục chưa xong và đã tới giờ làm (Data 2 từ chối check-in trước giờ đã xếp)."""
    now = now or now_utc()
    version, items = plan_items(pair_id, user_id)
    refs = [
        PlanItemRef(
            id=i.id,
            concept_id=i.concept_id,
            label=item_label(i),
            due_date=to_local(i.scheduled_start).date() if i.scheduled_start else to_local(now).date(),
        )
        for i in items
        if i.status == ItemStatus.SCHEDULED and (i.scheduled_start is None or i.scheduled_start <= now)
    ]
    refs.sort(key=lambda r: r.due_date)
    return version, refs[:20]


def concept_refs(concept_ids: list[str]) -> list[ConceptRef]:
    if not concept_ids:
        return []
    with database() as db:
        marks = ",".join("?" * len(concept_ids))
        rows = {
            r["id"]: r
            for r in db.execute(f"SELECT id,name,description FROM concepts WHERE id IN ({marks})", concept_ids)
        }
    return [
        ConceptRef(id=c, name=rows[c]["name"] if c in rows else c, description=rows[c]["description"] if c in rows else None)
        for c in concept_ids
    ]


def concept_names(concept_ids: list[str]) -> dict[str, str]:
    return {c.id: c.name for c in concept_refs(list(dict.fromkeys(concept_ids)))}


def strong_concepts(user_id: int) -> set[str]:
    theta = get_settings().partner_strength_theta
    with database() as db:
        rows = db.execute(
            "SELECT concept_id FROM user_concepts WHERE user_id=? AND role='offer' AND theta>=?", (user_id, theta)
        ).fetchall()
    return {r["concept_id"] for r in rows}


@dataclass
class CheckinContext:
    learner_name: str
    partner_id: int
    partner_name: str
    concepts: list[ConceptRef]
    open_items: list[PlanItemRef]
    plan_version: int | None = None
    partner_strengths: set[str] = field(default_factory=set)

    @property
    def concept_names(self) -> dict[str, str]:
        return {c.id: c.name for c in self.concepts}


def load_context(checkin: Checkin) -> CheckinContext:
    info = get_pair_for_user(checkin.user_id)
    version, items = open_plan_items(info.pair_id, checkin.user_id)
    concept_ids = list(dict.fromkeys(i.concept_id for i in items))
    concepts = concept_refs(concept_ids)
    for c in concepts:  # concept không có trong danh mục Data 1: mô tả bằng việc trong plan
        if c.description is None:
            c.description = next(i.label for i in items if i.concept_id == c.id)
    return CheckinContext(
        learner_name=info.me.display_name,
        partner_id=info.partner.id,
        partner_name=info.partner.display_name,
        concepts=concepts,
        open_items=items,
        plan_version=version,
        partner_strengths=strong_concepts(info.partner.id),
    )


def find_plan_item(pair_id: int, user_id: int, plan_item_id: str):
    version, items = plan_items(pair_id, user_id)
    return version, next((i for i in items if i.id == plan_item_id), None)


def _report_completion(checkin: Checkin, plan_item_id: str) -> int:
    """Gửi sự kiện hoàn thành cho Data 2. Trả về plan_version đã dùng."""
    from ..services.plans import PlanService

    version, item = find_plan_item(checkin.pair_id, checkin.user_id, plan_item_id)
    if item is None or version is None:
        raise PairAccessError("Mục này không thuộc plan của bạn.")
    if item.status == ItemStatus.COMPLETED:
        return version
    event = CompletionEvent(
        event_id=f"checkin:{checkin.id}",
        plan_item_id=plan_item_id,
        pair_id=checkin.pair_id,
        user_id=checkin.user_id,
        plan_version=version,
        confirmed_at=now_utc(),
        confirmed=True,
    )
    try:
        PlanService().complete(event)
    except PlanError as e:
        raise PairAccessError(e.message) from e
    return version


def complete_checkin(db: Session, checkin: Checkin, plan_item_id: str | None, ctx: CheckinContext | None = None) -> None:
    """Đánh dấu done, báo Data 2 mục plan đã xong, báo partner."""
    if plan_item_id:
        # Gọi Data 2 trước khi ghi bảng của mình để hai kết nối SQLite không giữ khóa cùng lúc.
        db.commit()
        checkin.plan_version = _report_completion(checkin, plan_item_id)
    checkin.plan_item_id = plan_item_id
    checkin.status = CheckinStatus.DONE
    checkin.completed_at = now_utc()
    db.flush()

    ctx = ctx or load_context(checkin)
    result = checkin.ai_result or {}
    bridge = [c for c in result.get("concepts", []) if c in ctx.partner_strengths]
    result = {**result, "bridge_concepts": bridge}
    checkin.ai_result = result

    summary = result.get("summary_for_partner") or result.get("description") or ""
    if not summary:
        label = None
        if plan_item_id:
            _, item = find_plan_item(checkin.pair_id, checkin.user_id, plan_item_id)
            label = item_label(item) if item else None
        summary = f"{ctx.learner_name} vừa check-in" + (f": {label.lower()}." if label else ".")
    message = summary if summary.startswith(ctx.learner_name) else f"{ctx.learner_name}: {summary}"
    if bridge:
        message += f" Phần này bạn mạnh, có thể chỉ {ctx.learner_name} vài phút."
    db.commit()
    notify(ctx.partner_id, message[:240], kind="checkin", title=f"{ctx.learner_name} vừa check-in")
    # Vòng AI: tính lại tiến độ cặp (Data 1) rồi để coach (Data 2) xem có cần can thiệp không.
    from ..loop.pairing import ensure_for_user
    from ..loop.trigger import after_activity

    pair_id = ensure_for_user(checkin.user_id)
    if pair_id:
        after_activity(pair_id)
