"""Compare recurring slots in a supplied representative week, in product timezone."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..onboarding.contracts import StudySlot
from .contracts import CommonSlot

PRODUCT_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_REFERENCE_WEEK = date(2026, 10, 5)
DAY_SECONDS = 24 * 60 * 60
WEEK_SECONDS = 7 * DAY_SECONDS
Interval = tuple[float, float]


def normalized_slots(slots: list[StudySlot], reference_week: date) -> list[Interval]:
    if reference_week.weekday() != 0:
        raise ValueError("Reference week must start on Monday")
    anchor = datetime.combine(reference_week, time(), PRODUCT_ZONE)
    intervals: list[Interval] = []
    for slot in slots:
        day = reference_week + timedelta(days=slot.day_of_week)
        start = datetime.combine(day, slot.start_time, ZoneInfo(slot.timezone)).astimezone(PRODUCT_ZONE)
        end = datetime.combine(day, slot.end_time, ZoneInfo(slot.timezone)).astimezone(PRODUCT_ZONE)
        lo = (start - anchor).total_seconds() % WEEK_SECONDS
        hi = lo + (end - start).total_seconds()
        intervals.append((lo, hi))
    merged: list[Interval] = []
    for lo, hi in sorted(set(intervals)):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    # A Sunday slot crossing the week boundary is still one slot, including when it overlaps Monday's input.
    while len(merged) > 1 and merged[-1][1] >= WEEK_SECONDS + merged[0][0]:
        merged[-1] = (merged[-1][0], max(merged[-1][1], WEEK_SECONDS + merged[0][1]))
        merged.pop(0)
    return merged


def common_slots(a: list[StudySlot], b: list[StudySlot],
                 reference_week: date = DEFAULT_REFERENCE_WEEK) -> tuple[list[CommonSlot], int]:
    left, right = normalized_slots(a, reference_week), normalized_slots(b, reference_week)
    # Maximum one-to-one slot matching: a long slot cannot masquerade as two weekly commitments.
    intersections = {}
    for i, (a_lo, a_hi) in enumerate(left):
        for j, (b_lo, b_hi) in enumerate(right):
            overlaps = [(max(a_lo, b_lo + shift), min(a_hi, b_hi + shift))
                        for shift in (-WEEK_SECONDS, 0, WEEK_SECONDS)
                        if max(a_lo, b_lo + shift) < min(a_hi, b_hi + shift)]
            if overlaps:
                intersections[i, j] = sorted(overlaps, key=lambda slot: (-(slot[1] - slot[0]), slot[0]))[0]
    edges = [[j for j in range(len(right)) if (i, j) in intersections] for i in range(len(left))]
    owners: dict[int, int] = {}

    def assign(i: int, seen: set[int]) -> bool:
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owners or assign(owners[j], seen):
                owners[j] = i
                return True
        return False

    for i in range(len(left)):
        assign(i, set())
    anchor = datetime.combine(reference_week, time(), PRODUCT_ZONE)
    shared = [CommonSlot(starts_at=anchor + timedelta(seconds=intersections[i, j][0]),
                         ends_at=anchor + timedelta(seconds=intersections[i, j][1]))
              for j, i in owners.items()]
    return sorted(shared, key=lambda item: (item.starts_at, item.ends_at)), min(len(left), len(right))
