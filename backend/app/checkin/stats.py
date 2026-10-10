"""Số liệu chất lượng và chi phí của AI Vision (tổng hợp, không chứa thông tin cá nhân)."""
from __future__ import annotations

import datetime as dt
import statistics

from sqlalchemy import func

from .config import get_settings
from .db import session_factory
from .models import Checkin, CheckinStatus
from .timeutil import now_utc, study_day


def _cost_since(since: dt.datetime) -> float:
    with session_factory()() as s:
        return float(s.query(func.coalesce(func.sum(Checkin.cost_usd), 0.0)).filter(Checkin.created_at >= since).scalar() or 0)


def _day_start_utc() -> dt.datetime:
    """Đầu ngày học hôm nay (giờ VN) đổi ra UTC."""
    from .timeutil import tz

    s = get_settings()
    local = dt.datetime.combine(study_day(), dt.time(hour=s.day_cutoff_hour), tzinfo=tz())
    return local.astimezone(dt.UTC)


def other_ai_cost_today() -> float:
    try:
        from ..loop.ai_budget import cost_since

        return sum(cost_since(_day_start_utc()).values())
    except Exception:
        return 0.0


def budget_left_usd() -> float:
    """Trần chung cho mọi phần AI: AI Vision + chia việc plan + xếp hạng ghép cặp."""
    return get_settings().daily_budget_usd - _cost_since(_day_start_utc()) - other_ai_cost_today()


def summary(days: int = 7) -> dict:
    since = now_utc() - dt.timedelta(days=days)
    with session_factory()() as s:
        rows = s.query(Checkin).filter(Checkin.created_at >= since).all()
    total = len(rows)
    by_status = {k: sum(r.status == k for r in rows) for k in sorted(CheckinStatus.ALL)}
    analysed = [r for r in rows if r.model and r.model != "fake" or r.confidence is not None]
    suggested = [r for r in rows if r.suggested_plan_item_id and r.status == CheckinStatus.DONE]
    corrected = sum(r.user_corrected for r in suggested)
    auto_done = [r for r in rows if r.status == CheckinStatus.DONE and not r.user_corrected and r.suggested_plan_item_id
                 and r.plan_item_id == r.suggested_plan_item_id]
    latencies = sorted(r.processing_ms for r in rows if r.processing_ms)
    by_day: dict[str, dict] = {}
    for r in rows:
        created = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=dt.UTC)
        key = created.astimezone(dt.UTC).date().isoformat()
        d = by_day.setdefault(key, {"date": key, "checkins": 0, "cost_usd": 0.0})
        d["checkins"] += 1
        d["cost_usd"] = round(d["cost_usd"] + (r.cost_usd or 0), 4)

    def pct(n: int, d: int) -> float | None:
        return round(n * 100 / d, 1) if d else None

    return {
        "days": days,
        "total_checkins": total,
        "by_status": by_status,
        # AI tự gắn đúng mục (người dùng không sửa) trên các check-in AI đã đề xuất mục
        "ai_accept_rate": pct(len(auto_done), len(suggested)),
        "user_correction_rate": pct(corrected, len(suggested)),
        "ask_again_rate": pct(by_status.get(CheckinStatus.NEEDS_CONFIRM, 0), total),
        "not_study_rate": pct(by_status.get(CheckinStatus.NOT_STUDY, 0), total),
        "avg_confidence": round(statistics.mean(r.confidence for r in analysed if r.confidence is not None), 2)
        if any(r.confidence is not None for r in analysed) else None,
        "latency_p50_ms": latencies[len(latencies) // 2] if latencies else None,
        "latency_p90_ms": latencies[int(len(latencies) * 0.9) - 1] if len(latencies) >= 10 else (latencies[-1] if latencies else None),
        "cost_usd": round(sum(r.cost_usd or 0 for r in rows), 4),
        "cost_today_usd": round(_cost_since(_day_start_utc()) + other_ai_cost_today(), 4),
        "vision_cost_today_usd": round(_cost_since(_day_start_utc()), 4),
        "daily_budget_usd": get_settings().daily_budget_usd,
        "model": get_settings().vision_model if get_settings().llm_provider == "openai" else "fake",
        "per_day": sorted(by_day.values(), key=lambda d: d["date"]),
    }
