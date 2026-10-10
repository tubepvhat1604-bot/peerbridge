import datetime as dt

from app.checkin.decision import decide
from app.checkin.schemas import PlanItemRef, VisionResult

D = dt.date(2026, 10, 12)
ITEMS = [
    PlanItemRef(id="a", concept_id="sql.join", label="JOIN bài 6", due_date=D + dt.timedelta(days=1)),
    PlanItemRef(id="b", concept_id="sql.join", label="JOIN 5 bài", due_date=D + dt.timedelta(days=3)),
    PlanItemRef(id="c", concept_id="sql.group_by", label="GROUP BY", due_date=D + dt.timedelta(days=2)),
    PlanItemRef(id="d", concept_id="py.basic", label="Python", due_date=D + dt.timedelta(days=5)),
]
NAMES = {"sql.join": "JOIN", "sql.group_by": "GROUP BY", "py.basic": "Python cơ bản"}


def r(concepts, conf, study=True):
    return VisionResult(is_study=study, concepts=concepts, description="x", confidence=conf)


def test_high_confidence_single_concept_picks_earliest_due():
    d = decide(r(["sql.join"], 0.9), ITEMS, NAMES)
    assert d.status == "done" and d.plan_item_id == "a"


def test_boundary_high_is_inclusive():
    assert decide(r(["sql.join"], 0.75), ITEMS, NAMES).status == "done"
    assert decide(r(["sql.join"], 0.7499), ITEMS, NAMES).status == "needs_confirm"


def test_medium_confidence_asks_with_three_options_matched_first():
    d = decide(r(["sql.group_by"], 0.6), ITEMS, NAMES)
    assert d.status == "needs_confirm"
    assert [o.plan_item_id for o in d.options][0] == "c"
    assert len(d.options) == 3
    assert d.plan_item_id == "c"


def test_two_concepts_even_if_confident_asks():
    d = decide(r(["sql.join", "sql.group_by"], 0.95), ITEMS, NAMES)
    assert d.status == "needs_confirm"
    assert [o.plan_item_id for o in d.options][:2] == ["a", "c"]


def test_low_confidence_shows_week_items():
    d = decide(r(["sql.join"], 0.2), ITEMS, NAMES, max_week=6)
    assert d.status == "needs_confirm"
    assert [o.plan_item_id for o in d.options] == ["a", "c", "b", "d"]


def test_no_match_shows_week_items():
    d = decide(r([], 0.9), ITEMS, NAMES)
    assert d.status == "needs_confirm" and d.plan_item_id is None and len(d.options) == 4


def test_not_study_still_offers_override():
    d = decide(r([], 0.9, study=False), ITEMS, NAMES)
    assert d.status == "not_study" and len(d.options) == 4


def test_failed_when_no_result():
    d = decide(None, ITEMS, NAMES)
    assert d.status == "failed" and len(d.options) == 4


def test_no_open_items():
    assert decide(r([], 0.9), [], NAMES).status == "done"
    assert decide(r([], 0.3), [], NAMES).status == "needs_confirm"


def test_option_carries_concept_name():
    d = decide(r(["sql.group_by"], 0.5), ITEMS, NAMES)
    assert d.options[0].concept_name == "GROUP BY"
