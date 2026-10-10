"""Chạy vòng AI: tính lại tiến độ cặp rồi cho coach đánh giá từng thành viên.

Gọi sau mỗi check-in được ghi nhận, khi người dùng mở trang Tổng quan, và theo chu kỳ (lifespan, nếu bật).
Mọi lỗi chỉ ghi log: vòng AI là phần phụ, không bao giờ làm hỏng thao tác chính của người dùng.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from ..db import database
from ..metrics.adapters import InputUnavailableError
from ..metrics.repository import MetricsRepository
from ..metrics.service import MeasurementService, MetricError
from ..metrics.time import study_date
from .measurement import TeamMeasurementSource

log = logging.getLogger("loop.trigger")


def recompute(pair_id: int) -> bool:
    """Tính lại số đo hôm nay cho cặp. Trả True nếu có số đo mới."""
    try:
        with database() as db:
            service = MeasurementService(MetricsRepository(db), TeamMeasurementSource())
            if not service.repository.eligible(pair_id):
                return False
            service.recompute(pair_id)
        return True
    except (InputUnavailableError, MetricError):
        return False
    except Exception:
        log.exception("Không tính được tiến độ cho cặp %s", pair_id)
        return False


def coach_members(pair_id: int) -> list[dict]:
    """Coach đánh giá từng thành viên (coach tự giới hạn tối đa 1 can thiệp mỗi người mỗi ngày, không nhắn giờ nghỉ)."""
    from .coach_bridge import get_team_coach_service

    decisions = []
    with database() as db:
        users = db.execute(
            "SELECT u.id, u.role, u.is_seed FROM users u JOIN pair_memberships m ON m.user_id=u.id WHERE m.pair_id=?",
            (pair_id,),
        ).fetchall()
    for u in users:
        try:
            decisions.append(_run(get_team_coach_service().evaluate(pair_id, dict(u))))
        except Exception:
            log.exception("Coach lỗi cho cặp %s, người %s", pair_id, u["id"])
    return decisions


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Đang ở trong event loop (hiếm): chạy ở luồng riêng để không chặn.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coro).result()


def after_activity(pair_id: int) -> None:
    if recompute(pair_id):
        coach_members(pair_id)


def pair_of(user_id: int) -> int | None:
    with database() as db:
        row = db.execute(
            "SELECT p.id FROM pair_memberships m JOIN pairs p ON p.id=m.pair_id WHERE m.user_id=? AND p.status='active'",
            (user_id,),
        ).fetchone()
    return row["id"] if row else None


def latest_is_today(pair_id: int) -> bool:
    with database() as db:
        row = db.execute("SELECT MAX(date) AS d FROM pair_metrics_daily WHERE pair_id=?", (pair_id,)).fetchone()
    return bool(row and row["d"] == study_date(datetime.now(UTC)).isoformat())


def run_all_pairs() -> int:
    with database() as db:
        ids = [r["id"] for r in db.execute("SELECT id FROM pairs WHERE status='active'")]
    for pid in ids:
        after_activity(pid)
    return len(ids)


async def periodic(minutes: int) -> None:
    while True:
        await asyncio.sleep(minutes * 60)
        try:
            await asyncio.to_thread(run_all_pairs)
        except Exception:
            log.exception("Vòng AI định kỳ lỗi")
