"""Dữ liệu trang Tổng quan: chỉ số thật của người dùng, các bước bắt đầu, việc sắp tới, hoạt động gần đây."""
from __future__ import annotations

import datetime as dt

from ..agents.plan_coach.contract import ItemStatus
from ..checkin import actions as vision
from ..checkin.db import session_factory
from ..checkin.models import Checkin, CheckinStatus
from ..checkin.service import _checked_in, pair_streak
from ..checkin.timeutil import now_utc, relative_vi, study_day, to_local, week_bounds
from ..db import database
from ..repositories.profiles import ProfileRepository
from . import notifications


def _profile_completion(bundle: dict | None) -> tuple[int, list[str]]:
    """% hồ sơ hoàn thiện và các mục còn thiếu (những gì giúp ghép cặp và lập kế hoạch tốt hơn)."""
    if not bundle:
        return 0, ["Mục tiêu học tập"]
    p = bundle["profile"]
    checks = [
        ("Mục tiêu học tập", bool(p.get("learning_goals"))),
        ("Điều bạn cần hỗ trợ", bool(bundle.get("needs_help_with"))),
        ("Điều bạn có thể hỗ trợ", bool(bundle.get("can_help_with"))),
        ("Trường hoặc ngành", bool(p.get("school") or p.get("major"))),
        ("Giới thiệu ngắn", bool((p.get("bio") or "").strip())),
    ]
    done = sum(ok for _, ok in checks)
    return round(done * 100 / len(checks)), [name for name, ok in checks if not ok]


def _when(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def build(user_id: int) -> dict:
    with database() as db:
        bundle = ProfileRepository(db).get_profile_bundle(user_id)
        pending_in = db.execute(
            "SELECT COUNT(*) FROM connection_requests WHERE recipient_id=? AND status='PENDING'", (user_id,)
        ).fetchone()[0]
        connected = db.execute(
            "SELECT COUNT(*) FROM peer_matches WHERE user_a_id=? OR user_b_id=?", (user_id, user_id)
        ).fetchone()[0]
        sessions = db.execute(
            """SELECT s.id, s.topic, s.scheduled_start, s.learner_id, s.helper_id FROM study_sessions s
               WHERE (s.learner_id=? OR s.helper_id=?) AND s.scheduled_start IS NOT NULL AND s.scheduled_start >= ?
               ORDER BY s.scheduled_start LIMIT 2""",
            (user_id, user_id, (now_utc() - dt.timedelta(hours=1)).isoformat()),
        ).fetchall()

    completion, missing = _profile_completion(bundle)
    name = bundle["profile"]["display_name"] if bundle else "bạn"

    try:
        pair = vision.get_pair_for_user(user_id)
    except vision.PairAccessError:
        pair = None

    plan = {"has_plan": False, "week_total": 0, "week_done": 0, "minutes_done": 0, "minutes_total": 0, "next": []}
    checkin = {"checked_in_today": False, "partner_checked_in_today": False, "streak": 0, "total_done": 0,
               "partner_latest": None}
    if pair:
        version, items = vision.plan_items(pair.pair_id, user_id)
        today = study_day()
        start, end = week_bounds(today)

        def day(i):
            return to_local(i.scheduled_start).date() if i.scheduled_start else None

        week = [i for i in items if day(i) and start <= day(i) <= end]
        upcoming = sorted(
            (i for i in items if i.status == ItemStatus.SCHEDULED and i.scheduled_start),
            key=lambda i: i.scheduled_start,
        )
        plan = {
            "today_total": sum(day(i) == today for i in items),
            "today_done": sum(day(i) == today and i.status == ItemStatus.COMPLETED for i in items),
            "has_plan": version is not None,
            "week_total": len(week),
            "week_done": sum(i.status == ItemStatus.COMPLETED for i in week),
            "minutes_total": sum(i.est_minutes for i in week),
            "minutes_done": sum(i.est_minutes for i in week if i.status == ItemStatus.COMPLETED),
            "next": [
                {"id": i.id, "label": vision.item_label(i), "concept_id": i.concept_id,
                 "scheduled_start": _when(i.scheduled_start), "est_minutes": i.est_minutes,
                 "due_now": i.scheduled_start <= now_utc()}
                for i in upcoming[:3]
            ],
        }
        with session_factory()() as s:
            latest = (
                s.query(Checkin)
                .filter(Checkin.user_id == pair.partner.id, Checkin.status == CheckinStatus.DONE)
                .order_by(Checkin.created_at.desc())
                .first()
            )
            checkin = {
                "checked_in_today": _checked_in(s, user_id, today),
                "partner_checked_in_today": _checked_in(s, pair.partner.id, today),
                "streak": pair_streak(s, pair.user_a, pair.user_b, today),
                "total_done": s.query(Checkin).filter(Checkin.user_id == user_id, Checkin.status == CheckinStatus.DONE).count(),
                "partner_latest": None if latest is None else {
                    "headline": (latest.ai_result or {}).get("summary_for_partner")
                    or (latest.ai_result or {}).get("description") or f"{pair.partner.display_name} vừa check-in",
                    "relative": relative_vi(latest.created_at),
                },
            }

    steps = [
        {"key": "profile", "title": "Cho biết mục tiêu học tập", "done": "Mục tiêu học tập" not in missing,
         "page": "profile", "hint": "Mục tiêu và điều bạn cần, điều bạn giỏi giúp ghép đúng người."},
        {"key": "connect", "title": "Kết nối với một bạn học", "done": pair is not None,
         "page": "matching", "hint": "Gửi lời mời hoặc chấp nhận lời mời của bạn khác."},
        {"key": "plan", "title": "Lập kế hoạch tuần", "done": plan["has_plan"],
         "page": "plan", "hint": "Hai bạn chốt mục tiêu, AI chia việc theo giờ rảnh."},
        {"key": "checkin", "title": "Check-in buổi học đầu tiên", "done": checkin["total_done"] > 0,
         "page": "checkin", "hint": "Chụp màn hình hoặc vở lúc học, AI ghi nhận giúp."},
    ]

    progress = _pair_progress(user_id, pair) if pair else None
    coach = _latest_coach(user_id)

    notes = notifications.recent(user_id, 6)
    activity = [
        {"id": n["id"], "kind": n["kind"], "title": n["title"], "body": n["body"], "page": n["page"],
         "relative": relative_vi(dt.datetime.fromisoformat(n["created_at"])), "unread": n["read_at"] is None}
        for n in notes
    ]

    return {
        "display_name": name,
        "profile_completion": completion,
        "profile_missing": missing,
        "pending_invites": pending_in,
        "connections": connected,
        "pair": None if pair is None else {"pair_id": pair.pair_id, "partner_id": pair.partner.id,
                                          "partner_name": pair.partner.display_name},
        "plan": plan,
        "checkin": checkin,
        "sessions": [
            {"id": r["id"], "topic": r["topic"], "scheduled_start": r["scheduled_start"]} for r in sessions
        ],
        "steps": steps,
        "progress": progress,
        "coach": coach,
        "activity": activity,
        "unread": notifications.unread_count(user_id),
    }


def _pair_progress(user_id: int, pair) -> dict | None:
    """Số đo tiến độ của Data 1 cho cặp (tính lại nếu hôm nay chưa có), nhìn từ phía người đang xem."""
    from ..loop.pairing import ensure_for_user
    from ..loop.trigger import after_activity, latest_is_today
    from ..metrics.repository import MetricsRepository

    pair_id = ensure_for_user(user_id)
    if not pair_id:
        return None
    if not latest_is_today(pair_id):
        after_activity(pair_id)
    with database() as db:
        repo = MetricsRepository(db)
        if repo.pair_row(pair_id) is None:
            return None
        m = repo.latest(repo.context(pair_id))
    if m is None:
        return {"available": False, "reason": "Cả hai cần có kế hoạch và bắt đầu check-in để đo tiến độ."}
    me, other = (m.learner_a, m.learner_b) if m.learner_a.user_id == user_id else (m.learner_b, m.learner_a)
    risk = m.risk_a if m.learner_a.user_id == user_id else m.risk_b

    def side(lp):
        return {"pacing": round(min(lp.pacing, 2.0), 2) if lp.has_due_workload else None,
                "completed_minutes": round(lp.completed_minutes), "due_minutes": round(lp.due_minutes)}

    return {
        "available": True,
        "as_of": m.computed_at.isoformat(),
        "me": side(me),
        "partner": side(other),
        "pair_score": round(m.pair_score, 2),
        "gap": round(m.gap, 2),
        "needs_attention": m.needs_attention,
        "i_am_lagging": m.lagging_member == user_id,
        "my_risk": round(risk.score, 2) if risk.score is not None else None,
        "streak": m.streak,
    }


def _latest_coach(user_id: int) -> dict | None:
    import json

    with database() as db:
        row = db.execute(
            "SELECT action, decision, delivery_status, created_at FROM pb_interventions WHERE user_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    decision = json.loads(row["decision"])
    return {"action": row["action"], "text": decision.get("text"), "source": decision.get("message_source", "template"),
            "status": row["delivery_status"], "created_at": row["created_at"],
            "proposal_id": decision.get("proposal_id")}
