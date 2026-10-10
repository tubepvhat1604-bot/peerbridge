from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

STUDY_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
STUDY_CUTOFF = time(3)


def require_aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Measurement timestamps must include a timezone")
    return timestamp


def study_date(timestamp: datetime) -> date:
    local = require_aware(timestamp).astimezone(STUDY_ZONE)
    return local.date() - timedelta(days=1) if local.time() < STUDY_CUTOFF else local.date()


def study_day_end(day: date) -> datetime:
    """Exclusive end: 03:00 on the next calendar day in the product timezone."""
    return datetime.combine(day + timedelta(days=1), STUDY_CUTOFF, STUDY_ZONE)
