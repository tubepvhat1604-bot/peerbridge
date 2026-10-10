"""Thời gian theo giờ Việt Nam.

Quy tắc ngày học: check-in trước `day_cutoff_hour` (mặc định 3h sáng) tính cho hôm trước.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from .config import get_settings


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def to_local(t: dt.datetime) -> dt.datetime:
    if t.tzinfo is None:  # SQLite trả datetime không múi giờ: coi là UTC
        t = t.replace(tzinfo=dt.UTC)
    return t.astimezone(tz())


def study_day(t: dt.datetime | None = None) -> dt.date:
    local = to_local(t or now_utc())
    if local.hour < get_settings().day_cutoff_hour:
        local -= dt.timedelta(days=1)
    return local.date()


def week_bounds(day: dt.date) -> tuple[dt.date, dt.date]:
    """Thứ 2 → Chủ nhật của tuần chứa `day`."""
    start = day - dt.timedelta(days=day.weekday())
    return start, start + dt.timedelta(days=6)


def in_quiet_hours(t: dt.datetime | None = None) -> bool:
    start, end = get_settings().quiet_hours
    h = to_local(t or now_utc()).hour
    return h >= start or h < end if start > end else start <= h < end


def relative_vi(t: dt.datetime | None, ref: dt.datetime | None = None) -> str:
    if t is None:
        return ""
    ref = ref or now_utc()
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.UTC)
    seconds = max(0, int((ref - t).total_seconds()))
    if seconds < 60:
        return "vừa xong"
    if seconds < 3600:
        return f"{seconds // 60} phút trước"
    if seconds < 86400:
        return f"{seconds // 3600} giờ trước"
    days = seconds // 86400
    if days == 1:
        return "hôm qua"
    if days < 7:
        return f"{days} ngày trước"
    return to_local(t).strftime("%d/%m")
