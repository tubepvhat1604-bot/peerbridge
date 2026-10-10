import datetime as dt

from app.checkin import timeutil
from checkin_helpers import vision_env


def utc(y, m, d, h, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=dt.UTC)


def test_study_day_cutoff(vision_env):
    # 01:30 giờ VN ngày 13/10 = 18:30 UTC ngày 12/10 -> tính cho ngày 12/10
    assert timeutil.study_day(utc(2026, 10, 12, 18, 30)) == dt.date(2026, 10, 12)
    # 03:30 giờ VN ngày 13/10 = 20:30 UTC ngày 12/10 -> ngày 13/10
    assert timeutil.study_day(utc(2026, 10, 12, 20, 30)) == dt.date(2026, 10, 13)


def test_naive_datetime_treated_as_utc(vision_env):
    assert timeutil.study_day(dt.datetime(2026, 10, 12, 20, 30)) == dt.date(2026, 10, 13)


def test_quiet_hours(vision_env):
    assert timeutil.in_quiet_hours(utc(2026, 10, 12, 16))  # 23:00 VN
    assert timeutil.in_quiet_hours(utc(2026, 10, 12, 23))  # 06:00 VN
    assert not timeutil.in_quiet_hours(utc(2026, 10, 12, 1))  # 08:00 VN


def test_week_bounds():
    start, end = timeutil.week_bounds(dt.date(2026, 10, 15))  # thứ 5
    assert start == dt.date(2026, 10, 12) and end == dt.date(2026, 10, 18)


def test_relative_vi():
    ref = utc(2026, 10, 12, 12)
    assert timeutil.relative_vi(ref - dt.timedelta(seconds=10), ref) == "vừa xong"
    assert timeutil.relative_vi(ref - dt.timedelta(minutes=25), ref) == "25 phút trước"
    assert timeutil.relative_vi(ref - dt.timedelta(hours=3), ref) == "3 giờ trước"
    assert timeutil.relative_vi(ref - dt.timedelta(days=1, hours=2), ref) == "hôm qua"

__all__ = ["vision_env"]  # fixture dùng chung
