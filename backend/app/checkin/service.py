"""Nghiệp vụ check-in: tạo, xác nhận, cảm xúc/bình luận, nhắc bạn, dữ liệu trang chủ, streak."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..agents.plan_coach.contract import ItemStatus
from ..db import database
from .actions import (
    PairAccessError,
    PairInfo,
    Person,
    complete_checkin,
    concept_names,
    display_name,
    find_plan_item,
    get_pair_for_user,
    item_label,
    load_context,
    plan_items,
)
from .config import get_settings
from .imaging import process_image
from .models import Checkin, CheckinStatus, Nudge, Reaction
from .notify import notify
from .schemas import CheckinOut, FeedOut, OptionOut, PersonProgress, ReactionOut
from .storage import get_storage
from .timeutil import in_quiet_hours, now_utc, relative_vi, study_day, to_local, week_bounds


class ServiceError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ---------------------------------------------------------------- tạo check-in
def _guard_new(db: Session, user_id: int, checkin_id: str) -> tuple[Checkin | None, PairInfo]:
    try:
        info = get_pair_for_user(user_id)
    except PairAccessError as e:
        raise ServiceError(403, str(e)) from e
    existing = db.get(Checkin, checkin_id)
    if existing is not None:
        if existing.user_id != user_id:
            raise ServiceError(409, "Mã check-in bị trùng. Hãy thử gửi lại.")
        return existing, info
    today = study_day()
    count = db.scalar(
        select(func.count()).select_from(Checkin).where(Checkin.user_id == user_id, Checkin.study_day == today)
    )
    if count >= get_settings().max_checkins_per_day:
        raise ServiceError(429, "Hôm nay bạn đã check-in đủ số lần tối đa. Mai gặp lại nhé.")
    return None, info


def create_photo_checkin(db: Session, user_id: int, checkin_id: str, raw: bytes, note: str | None) -> tuple[Checkin, bool]:
    """Trả (checkin, is_new). is_new=False nghĩa là client gửi trùng: không chạy lại AI."""
    existing, info = _guard_new(db, user_id, checkin_id)
    if existing is not None:
        return existing, False
    img = process_image(raw)  # ném ImageError nếu ảnh hỏng
    path = f"{info.pair_id}/{user_id}/{checkin_id}.jpg"
    get_storage().save(path, img.data, img.media_type)
    checkin = Checkin(
        id=checkin_id,
        user_id=user_id,
        pair_id=info.pair_id,
        kind="photo",
        image_path=path,
        note=(note or "").strip()[: get_settings().note_max_chars] or None,
        status=CheckinStatus.PROCESSING,
        study_day=study_day(),
    )
    db.add(checkin)
    db.commit()
    return checkin, True


def create_text_checkin(db: Session, user_id: int, checkin_id: str, note: str, plan_item_id: str | None = None) -> tuple[Checkin, bool]:
    existing, info = _guard_new(db, user_id, checkin_id)
    if existing is not None:
        return existing, False
    if plan_item_id is not None:
        _, item = find_plan_item(info.pair_id, user_id, plan_item_id)
        if item is None:
            raise ServiceError(400, "Việc này không thuộc kế hoạch của bạn.")
    checkin = Checkin(
        id=checkin_id,
        user_id=user_id,
        pair_id=info.pair_id,
        kind="text",
        note=note.strip()[: get_settings().note_max_chars],
        status=CheckinStatus.PROCESSING,
        study_day=study_day(),
    )
    db.add(checkin)
    db.commit()
    if plan_item_id is not None:
        try:
            complete_checkin(db, checkin, plan_item_id)
        except PairAccessError as e:
            raise ServiceError(400, str(e)) from e
    return checkin, True


# ---------------------------------------------------------------- đọc / xác nhận
def get_owned(db: Session, user_id: int, checkin_id: str) -> Checkin:
    checkin = db.get(Checkin, checkin_id)
    if checkin is None or checkin.user_id != user_id:
        raise ServiceError(404, "Không tìm thấy check-in.")
    return checkin


def get_visible(db: Session, user_id: int, checkin_id: str) -> Checkin:
    checkin = db.get(Checkin, checkin_id)
    if checkin is None:
        raise ServiceError(404, "Không tìm thấy check-in.")
    if checkin.user_id == user_id:
        return checkin
    try:
        info = get_pair_for_user(user_id)
    except PairAccessError as e:
        raise ServiceError(404, "Không tìm thấy check-in.") from e
    if checkin.pair_id != info.pair_id or checkin.status != CheckinStatus.DONE:
        raise ServiceError(404, "Không tìm thấy check-in.")
    return checkin


def confirm(db: Session, user_id: int, checkin_id: str, plan_item_id: str | None) -> Checkin:
    checkin = get_owned(db, user_id, checkin_id)
    if checkin.status == CheckinStatus.DONE:
        return checkin
    if checkin.status == CheckinStatus.PROCESSING:
        raise ServiceError(409, "Ảnh vẫn đang được phân tích. Chờ vài giây nhé.")
    allowed = {o["plan_item_id"] for o in (checkin.options or [])}
    if plan_item_id is not None and plan_item_id not in allowed:
        # Cho phép chọn bất kỳ mục chưa xong nào của chính mình (lỡ không có trong lựa chọn).
        _, item = find_plan_item(checkin.pair_id, user_id, plan_item_id)
        if item is None:
            raise ServiceError(400, "Mục này không có trong plan của bạn.")
    was_not_study = checkin.status == CheckinStatus.NOT_STUDY
    checkin.user_corrected = was_not_study or (
        checkin.suggested_plan_item_id is not None and plan_item_id != checkin.suggested_plan_item_id
    )
    try:
        complete_checkin(db, checkin, plan_item_id)
    except PairAccessError as e:
        db.rollback()
        raise ServiceError(400, str(e)) from e
    return checkin


# ---------------------------------------------------------------- cảm xúc / bình luận
def react(db: Session, user_id: int, checkin_id: str, emoji: str | None, comment: str | None) -> Checkin:
    checkin = get_visible(db, user_id, checkin_id)
    if checkin.user_id == user_id:
        raise ServiceError(400, "Bạn chỉ thả cảm xúc cho check-in của bạn học.")
    comment = (comment or "").strip()
    if not emoji and not comment:
        raise ServiceError(400, "Hãy chọn một biểu tượng hoặc viết bình luận.")
    if len(comment) > get_settings().comment_max_chars:
        raise ServiceError(400, f"Bình luận tối đa {get_settings().comment_max_chars} ký tự.")
    if emoji and not comment:
        existing = db.scalars(
            select(Reaction).where(
                Reaction.checkin_id == checkin_id, Reaction.user_id == user_id, Reaction.emoji == emoji,
                Reaction.comment.is_(None),
            )
        ).first()
        if existing:  # bấm lại = bỏ cảm xúc
            db.delete(existing)
            db.commit()
            db.refresh(checkin)
            return checkin
    db.add(Reaction(checkin_id=checkin_id, user_id=user_id, emoji=emoji, comment=comment or None))
    db.commit()
    if emoji and not comment:
        notify(checkin.user_id, "", kind="reaction", title=f"{display_name(user_id)} thả {emoji} cho check-in của bạn")
    if comment:
        notify(checkin.user_id, comment[:240], kind="comment", title=f"{display_name(user_id)} bình luận check-in của bạn")
    db.refresh(checkin)
    return checkin


# ---------------------------------------------------------------- nhắc bạn
def _nudge_state(db: Session, info: PairInfo, partner_today: bool) -> tuple[bool, str | None]:
    if partner_today:
        return False, f"{info.partner.display_name} đã check-in hôm nay rồi."
    if in_quiet_hours():
        start, end = get_settings().quiet_hours
        return False, f"Đang giờ nghỉ ({start}:00–{end}:00). Nhắc lại sau nhé."
    last = db.scalars(
        select(Nudge)
        .where(Nudge.from_user == info.me.id, Nudge.to_user == info.partner.id)
        .order_by(desc(Nudge.created_at))
        .limit(1)
    ).first()
    if last is not None:
        created = last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=dt.UTC)
        wait = dt.timedelta(hours=get_settings().nudge_cooldown_hours) - (now_utc() - created)
        if wait.total_seconds() > 0:
            hours = max(1, round(wait.total_seconds() / 3600))
            return False, f"Bạn vừa nhắc rồi. Có thể nhắc lại sau khoảng {hours} giờ."
    return True, None


def nudge(db: Session, user_id: int, pair_id: int) -> str:
    try:
        info = get_pair_for_user(user_id)
    except PairAccessError as e:
        raise ServiceError(403, str(e)) from e
    if info.pair_id != pair_id:
        raise ServiceError(403, "Bạn không thuộc cặp học này.")
    partner_today = _checked_in(db, info.partner.id, study_day())
    ok, reason = _nudge_state(db, info, partner_today)
    if not ok:
        raise ServiceError(409, reason or "Chưa nhắc được lúc này.")
    delivered = notify(info.partner.id, "Mở app và chụp một tấm lúc bạn học nhé.", kind="nudge",
                       title=f"{info.me.display_name} đang chờ bạn check-in hôm nay")
    db.add(Nudge(pair_id=pair_id, from_user=user_id, to_user=info.partner.id, delivered=delivered))
    db.commit()
    return f"Đã nhắc {info.partner.display_name}."


# ---------------------------------------------------------------- trang chủ cặp
def _checked_in(db: Session, user_id: int, day: dt.date) -> bool:
    return bool(
        db.scalar(
            select(func.count()).select_from(Checkin).where(
                Checkin.user_id == user_id, Checkin.study_day == day, Checkin.status == CheckinStatus.DONE
            )
        )
    )


def pair_streak(db: Session, user_a: int, user_b: int, today: dt.date | None = None) -> int:
    """Số ngày liên tiếp CẢ HAI cùng có check-in. Hôm nay chưa đủ hai người thì tính đến hôm qua."""
    today = today or study_day()
    since = today - dt.timedelta(days=180)
    rows = db.execute(
        select(Checkin.user_id, Checkin.study_day).where(
            Checkin.user_id.in_([user_a, user_b]),
            Checkin.status == CheckinStatus.DONE,
            Checkin.study_day >= since,
        )
    ).all()
    days_a = {d for u, d in rows if u == user_a}
    days_b = {d for u, d in rows if u == user_b}
    both = days_a & days_b
    day = today if today in both else today - dt.timedelta(days=1)
    streak = 0
    while day in both:
        streak += 1
        day -= dt.timedelta(days=1)
    return streak


def _progress(db: Session, info: PairInfo, user: Person, today: dt.date) -> PersonProgress:
    week_start, week_end = week_bounds(today)
    _, items = plan_items(info.pair_id, user.id)

    def day(i):
        return to_local(i.scheduled_start).date() if i.scheduled_start else None

    week = [i for i in items if day(i) and week_start <= day(i) <= week_end]
    due = [i for i in items if day(i) and day(i) <= today]
    due_minutes = sum(i.est_minutes for i in due)
    pacing = None
    with database() as conn:
        metric = conn.execute(
            "SELECT pacing_a, pacing_b FROM pair_metrics_daily WHERE pair_id=? ORDER BY date DESC LIMIT 1",
            (info.pair_id,),
        ).fetchone()
    if not due_minutes:  # chưa có việc tới hạn: không ghi "tiến độ 100%" khi mới 0/0 việc
        pacing = None
    elif metric is not None:  # số chính thức từ Data 1
        pacing = metric["pacing_a"] if user.id == info.user_a else metric["pacing_b"]
    else:  # dự phòng: phút đã xong / phút đáng lẽ xong đến hôm nay
        pacing = round(sum(i.est_minutes for i in due if i.status == ItemStatus.COMPLETED) / due_minutes, 2)
    return PersonProgress(
        user_id=user.id,
        display_name=user.display_name,
        pacing=pacing,
        done_items=sum(1 for i in week if i.status == ItemStatus.COMPLETED),
        total_items=len(week),
        checked_in_today=_checked_in(db, user.id, today),
    )


def present(db: Session, checkin: Checkin, viewer_id: int, names: dict[str, str] | None = None) -> CheckinOut:
    owner_name = display_name(checkin.user_id)
    is_owner = viewer_id == checkin.user_id
    result = checkin.ai_result or {}
    concept_ids = result.get("concepts", [])
    if names is None:
        names = concept_names(concept_ids)
    plan_label = None
    if checkin.plan_item_id:
        _, item = find_plan_item(checkin.pair_id, checkin.user_id, checkin.plan_item_id)
        plan_label = item_label(item) if item else None

    bridge = None
    if checkin.status == CheckinStatus.DONE and result.get("bridge_concepts"):
        if is_owner:
            info = get_pair_for_user(viewer_id)
            bridge = f"{info.partner.display_name} mạnh phần này. Kẹt chỗ nào thì hỏi {info.partner.display_name} nhé."
        else:
            bridge = f"Phần này bạn mạnh, có thể chỉ {owner_name} vài phút."

    s = checkin.status
    if is_owner:
        headline = {
            CheckinStatus.PROCESSING: "Đang phân tích…",
            CheckinStatus.NEEDS_CONFIRM: "Bạn vừa học phần nào?",
            CheckinStatus.DONE: f"Đã ghi nhận: {plan_label or result.get('description') or 'buổi học hôm nay'}",
            CheckinStatus.NOT_STUDY: "Ảnh này chưa giống ảnh đang học",
            CheckinStatus.FAILED: "Chưa phân tích được. Chọn mục bạn vừa học",
        }[s]
    else:
        headline = result.get("summary_for_partner") or result.get("description") or f"{owner_name} vừa check-in"

    reactions = []
    for r in checkin.reactions:
        reactions.append(
            ReactionOut(user_id=r.user_id, display_name=display_name(r.user_id), emoji=r.emoji, comment=r.comment, relative=relative_vi(r.created_at))
        )

    show_options = is_owner and s in (CheckinStatus.NEEDS_CONFIRM, CheckinStatus.FAILED, CheckinStatus.NOT_STUDY)
    return CheckinOut(
        id=checkin.id,
        status=s,
        kind=checkin.kind,
        owner_id=checkin.user_id,
        owner_name=owner_name,
        image_url=get_storage().url(checkin.image_path) if checkin.image_path else None,
        note=checkin.note,
        created_at=checkin.created_at,
        relative=relative_vi(checkin.created_at),
        headline=headline,
        description=result.get("description"),
        concept_names=[names.get(c, c) for c in concept_ids],
        partner_summary=result.get("summary_for_partner"),
        bridge=bridge,
        plan_item_label=plan_label,
        options=[OptionOut(**o) for o in (checkin.options or [])] if show_options else [],
        reactions=reactions,
    )


def feed(db: Session, user_id: int) -> FeedOut:
    try:
        info = get_pair_for_user(user_id)
    except PairAccessError as e:
        raise ServiceError(403, str(e)) from e
    today = study_day()
    me_p = _progress(db, info, info.me, today)
    partner_p = _progress(db, info, info.partner, today)

    def latest(uid: int, statuses: set[str] | None = None) -> Checkin | None:
        q = select(Checkin).where(Checkin.user_id == uid)
        if statuses:
            q = q.where(Checkin.status.in_(statuses))
        return db.scalars(q.order_by(desc(Checkin.created_at)).limit(1)).first()

    partner_latest = latest(info.partner.id, {CheckinStatus.DONE})
    my_latest = latest(user_id)
    since = now_utc() - dt.timedelta(days=3)
    pending = list(
        db.scalars(
            select(Checkin)
            .where(
                Checkin.user_id == user_id,
                Checkin.status.in_([CheckinStatus.NEEDS_CONFIRM, CheckinStatus.FAILED]),
                Checkin.created_at >= since,
            )
            .order_by(desc(Checkin.created_at))
            .limit(5)
        )
    )
    history = list(
        db.scalars(
            select(Checkin)
            .where(Checkin.pair_id == info.pair_id, Checkin.status == CheckinStatus.DONE)
            .order_by(desc(Checkin.created_at))
            .limit(12)
        )
    )
    can_nudge, hint = _nudge_state(db, info, partner_p.checked_in_today)
    return FeedOut(
        provider_mode=get_settings().llm_provider,
        pair_id=info.pair_id,
        me=me_p,
        partner=partner_p,
        streak=pair_streak(db, info.user_a, info.user_b, today),
        partner_latest=present(db, partner_latest, user_id) if partner_latest else None,
        my_latest=present(db, my_latest, user_id) if my_latest else None,
        my_pending=[present(db, c, user_id) for c in pending if not my_latest or c.id != my_latest.id],
        history=[present(db, c, user_id) for c in history],
        can_nudge=can_nudge,
        nudge_hint=hint,
    )


def media_allowed(db: Session, user_id: int, path: str) -> bool:
    checkin = db.scalars(select(Checkin).where(Checkin.image_path == path).limit(1)).first()
    if checkin is None:
        return False
    if checkin.user_id == user_id:
        return True
    try:
        info = get_pair_for_user(user_id)
    except PairAccessError:
        return False
    return checkin.pair_id == info.pair_id and checkin.status == CheckinStatus.DONE


__all__ = [
    "ServiceError",
    "create_photo_checkin",
    "create_text_checkin",
    "get_owned",
    "confirm",
    "react",
    "nudge",
    "feed",
    "present",
    "pair_streak",
    "media_allowed",
    "load_context",
]
