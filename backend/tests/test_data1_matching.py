import asyncio
import json
from datetime import UTC, date, datetime
from math import nan

import pytest
from app.matching.availability import common_slots, normalized_slots
from app.matching.config import MatchingConfig
from app.matching.contracts import Components
from app.matching.engine import rank_candidates, result_for
from app.matching.filters import RejectionReason, rejection_reasons
from app.matching.reranking import StructuredReranker, rerank
from app.matching.scoring import harmonic_mean, match_level, score_pair
from app.onboarding.contracts import LearnerProfile, OnboardingInput, StudySlot, UserConcept
from pydantic import ValidationError


def learner(user_id=1, needs=("sql.join",), offers=("py.functions",), learning=(), **fields):
    slots = [StudySlot(day_of_week=day, start_time="19:00", end_time="20:00") for day in (1, 3)]
    onboarding = OnboardingInput(learning_goal=f"Goal {user_id}", committed_weekly_hours=5,
                                 availability=slots).model_copy(update=fields)
    concepts = [UserConcept(user_id=user_id, concept_id=concept_id, role=role,
                            self_level=level, theta=theta, n_attempts=0)
                for ids, role, level, theta in ((needs, "need", "unknown", -1),
                                               (offers, "offer", "strong", 1),
                                               (learning, "need", "learning", 0)) for concept_id in ids]
    return LearnerProfile(user_id=user_id, revision=1, status="confirmed", confirmed_at=datetime.now(UTC),
                          onboarding=onboarding, user_concepts=concepts, mappings=[], unmapped=[])


def opposite(user_id=2, **fields):
    return learner(user_id, needs=("py.functions",), offers=("sql.join",), **fields)


def test_exact_reciprocal_formula_weights_and_canonical_facts():
    a, b = learner(), opposite()
    total, c, facts = score_pair(a, b)
    assert (c.coverage_a_by_b, c.coverage_b_by_a, c.reciprocal_complementarity) == (1, 1, 1)
    assert c.concept_overlap == 0 and c.availability_overlap == 1 and c.commitment_similarity == 1
    assert total == pytest.approx(.35 + .20 + .20)
    assert facts.concepts_a_receives_from_b == ["sql.join"]
    assert facts.concepts_b_receives_from_a == ["py.functions"]
    assert score_pair(a, b) == score_pair(a, b)


def test_asymmetric_harmonic_mean_and_theta_offer_gate():
    a = learner(needs=("sql.join", "sql.group_by"))
    b = opposite()
    _, c, _ = score_pair(a, b)
    assert c.coverage_a_by_b == .5 and c.coverage_b_by_a == 1
    assert c.reciprocal_complementarity == pytest.approx(2 / 3)
    b.user_concepts[1].theta = .4999
    assert score_pair(a, b)[1].reciprocal_complementarity == 0
    b.user_concepts[1].theta = .5
    assert score_pair(a, b)[1].reciprocal_complementarity == pytest.approx(2 / 3)


@pytest.mark.parametrize("a,b,expected", [(0, 0, 0), (0, 1, 0), (1, 0, 0), (.25, .75, .375), (1, 1, 1)])
def test_harmonic_boundaries(a, b, expected):
    assert harmonic_mean(a, b) == expected


@pytest.mark.parametrize("a,b", [(-.1, 1), (1, 1.1), (nan, .5), (.5, float("inf"))])
def test_invalid_coverage_rejected(a, b):
    with pytest.raises(ValueError):
        harmonic_mean(a, b)


def test_learning_jaccard_and_commitment_available_input_mean():
    a = learner(learning=("sql.where", "sql.limit"), conscientiousness=.8, procrastination=.1)
    b = opposite(learning=("sql.where", "sql.order_by"), committed_weekly_hours=10,
                 conscientiousness=.4, procrastination=.7)
    total, c, _ = score_pair(a, b)
    assert c.concept_overlap == pytest.approx(1 / 3)
    assert c.commitment_similarity == pytest.approx((.5 + .6 + .4) / 3)
    # Learning needs also belong to the coverage denominator: each partner covers one of three needs.
    assert total == pytest.approx(.35 / 3 + .25 / 3 + .20 + .20 * .5)
    b.onboarding.procrastination = None
    assert score_pair(a, b)[1].commitment_similarity == pytest.approx((.5 + .6) / 2)
    b.onboarding.conscientiousness = None
    assert score_pair(a, b)[1].commitment_similarity == .5


@pytest.mark.parametrize("change,reason", [
    ({"committed_weekly_hours": 10.0001}, RejectionReason.HOURS),
    ({"availability": []}, RejectionReason.SLOTS),
    ({"deadline": date(2026, 11, 30)}, RejectionReason.DEADLINE),
])
def test_exact_hard_filter_rejections(change, reason):
    assert reason in rejection_reasons(learner(deadline=date(2026, 11, 1)), opposite(**change))


@pytest.mark.parametrize("deadline", [None, date(2026, 11, 1), date(2026, 11, 29), date(2026, 10, 4)])
def test_deadline_four_week_boundary_and_missing_optional(deadline):
    assert not rejection_reasons(learner(deadline=date(2026, 11, 1)), opposite(deadline=deadline,
                                                                                         committed_weekly_hours=10))


def test_self_draft_and_one_direction_level_semantics():
    assert RejectionReason.SELF in rejection_reasons(learner(), learner())
    b = opposite()
    b.status = "draft"
    assert RejectionReason.UNCONFIRMED in rejection_reasons(learner(), b)
    b.status = "confirmed"
    b.user_concepts = [item for item in b.user_concepts if item.role == "need"]
    assert not rejection_reasons(learner(), b)  # CONTEXT permits shared-commitment/overlap levels.
    assert result_for(learner(), b).reciprocal_score == 0
    assert result_for(learner(), b).match_level == "shared_commitment"


def test_two_independent_slots_timezone_conversion_and_duplicates():
    a = learner()
    b = opposite()
    for slot in b.onboarding.availability:
        slot.timezone = "UTC"
        slot.start_time = datetime.strptime("12:30", "%H:%M").time()
        slot.end_time = datetime.strptime("13:30", "%H:%M").time()
    slots, fewer = common_slots(a.onboarding.availability, b.onboarding.availability)
    assert len(slots) == fewer == 2
    assert all(slot.starts_at.hour == 19 and slot.starts_at.minute == 30 for slot in slots)
    b.onboarding.availability = [a.onboarding.availability[0]] * 3
    assert RejectionReason.SLOTS in rejection_reasons(a, b)


def test_one_long_slot_cannot_count_as_two_and_week_wrap():
    slots = [StudySlot(day_of_week=1, start_time="19:00", end_time="22:00")]
    split = [StudySlot(day_of_week=1, start_time="19:00", end_time="20:00"),
             StudySlot(day_of_week=1, start_time="21:00", end_time="22:00")]
    assert len(common_slots(slots, split)[0]) == 1
    wrap = [StudySlot(day_of_week=6, start_time="16:30", end_time="18:30", timezone="UTC")]
    assert normalized_slots(wrap, date(2026, 10, 5)) == [(603000, 610200)]
    assert len(common_slots(wrap, wrap)[0]) == 1
    monday = [StudySlot(day_of_week=0, start_time="00:30", end_time="01:30")]
    assert len(common_slots(wrap, monday)[0]) == 1


@pytest.mark.parametrize("reciprocal,overlap,same,level", [
    (1e-10, 0, True, "complementary"), (0, 1, True, "same_outcome"),
    (0, 1e-10, False, "concept_overlap"), (0, 0, False, "shared_commitment"),
])
def test_four_match_level_boundaries(reciprocal, overlap, same, level):
    assert match_level(reciprocal, overlap, same) == level


def test_deterministic_ties_top_five_and_private_facts():
    a = learner(conscientiousness=.93, communication_style="PRIVATE STYLE")
    ranked, rejected = rank_candidates(a, [opposite(i) for i in reversed(range(2, 10))] + [a])
    assert [r.candidate_user_id for r in ranked] == [2, 3, 4, 5, 6]
    assert rejected == {1: [RejectionReason.SELF]}
    for r in ranked:
        assert len(r.explanation.split(". ")) == 2
        assert r.facts.common_slots == common_slots(a.onboarding.availability, opposite().onboarding.availability)[0]
        assert "PRIVATE" not in r.model_dump_json()
        assert not {"conscientiousness", "procrastination", "communication_style"} & set(r.facts.model_dump())
        assert 0 <= r.total_score <= 1


def test_invalid_canonical_data_and_score_range_are_rejected():
    a = learner()
    a.user_concepts[0].concept_id = "sql.invented"
    with pytest.raises(ValueError):
        score_pair(a, opposite())
    with pytest.raises(ValidationError):
        Components(coverage_a_by_b=2, coverage_b_by_a=1, reciprocal_complementarity=1,
                   concept_overlap=1, availability_overlap=1, commitment_similarity=1)
    with pytest.raises(ValueError):
        MatchingConfig(complementarity_weight=.45)
    with pytest.raises(ValueError):
        MatchingConfig(candidate_limit=6)


def test_perfect_score_and_no_need_empty_coverage_boundaries():
    a = learner(needs=(), offers=(), learning=("sql.join",))
    b = learner(2, needs=(), offers=(), learning=("sql.join",))
    for profile in (a, b):
        profile.user_concepts.append(UserConcept(user_id=profile.user_id, concept_id="sql.join", role="offer",
                                                 self_level="learning", theta=.8, n_attempts=3))
    assert result_for(a, b).total_score == 1
    assert result_for(a, b).reciprocal_score == 1
    empty_a, empty_b = learner(needs=(), offers=()), learner(2, needs=(), offers=())
    assert result_for(empty_a, empty_b).reciprocal_score == 0
    assert result_for(empty_a, empty_b).component_scores.concept_overlap == 0


def test_adjacent_or_overlapping_inputs_do_not_inflate_slots():
    adjacent = [StudySlot(day_of_week=1, start_time="19:00", end_time="20:00"),
                StudySlot(day_of_week=1, start_time="20:00", end_time="21:00")]
    assert len(common_slots(adjacent, adjacent)[0]) == 1
    assert len(common_slots([], adjacent)[0]) == 0


def test_week_wrapping_interval_merges_all_overlapping_monday_inputs():
    slots = [StudySlot(day_of_week=6, start_time="16:30", end_time="18:30", timezone="UTC"),
             StudySlot(day_of_week=0, start_time="00:00", end_time="00:30"),
             StudySlot(day_of_week=0, start_time="01:00", end_time="01:15")]
    assert len(normalized_slots(slots, date(2026, 10, 5))) == 1
    assert len(common_slots(slots, slots)[0]) == 1


def test_top_k_and_hard_filters_precede_provider_input():
    a, draft = learner(), opposite(99)
    draft.status = "draft"
    ranked, rejected = rank_candidates(a, [draft, *[opposite(i) for i in range(2, 9)]],
                                       MatchingConfig(candidate_limit=3))
    assert len(ranked) == 3 and 99 in rejected
    assert all(r.candidate_user_id != 99 for r in ranked)


class FakeReranker:
    backend = "test_local"

    def __init__(self, output=None, error=None, delay=0):
        self.output, self.error, self.delay = output, error, delay

    async def rerank(self, candidates):
        self.received = candidates
        candidates[0].facts.concepts_a_receives_from_b = ["sql.fake"]
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.output


def rerank_rows():
    return rank_candidates(learner(), [opposite(2), opposite(3)])[0]


def valid_output():
    return {"candidates": [{"candidate_user_id": i, "rating": i, "match_level": "complementary"} for i in (2, 3)]}


def test_valid_llm_reorder_keeps_scores_facts_and_two_sentence_reasons():
    rows = rerank_rows()
    provider = FakeReranker(valid_output())
    result, metadata = asyncio.run(rerank(rows, provider))
    assert metadata.status == "applied" and [r.candidate_user_id for r in result] == [3, 2]
    assert result[0].total_score == rows[1].total_score
    assert result[1].facts == rows[0].facts and "sql.fake" not in result[1].model_dump_json()


@pytest.mark.parametrize("output", [
    {"candidates": [{"candidate_user_id": 999, "rating": 5, "match_level": "complementary"}]},
    {"candidates": []}, {"candidates": valid_output()["candidates"] * 2},
    {"candidates": [{"candidate_user_id": 2, "rating": 6, "match_level": "complementary"}]},
    {"candidates": [{"candidate_user_id": 2, "rating": True, "match_level": "complementary"}]},
    {"candidates": [{"candidate_user_id": 2, "rating": 5, "match_level": "same_outcome"},
                    {"candidate_user_id": 3, "rating": 5, "match_level": "complementary"}]},
    "bad json", {**valid_output(), "explanation": "Invented mastery"},
])
def test_invalid_rerank_falls_back(output):
    rows = rerank_rows()
    result, metadata = asyncio.run(rerank(rows, FakeReranker(output)))
    assert result == rows and metadata.status == "invalid_output"


@pytest.mark.parametrize("provider,status", [
    (FakeReranker(error=RuntimeError("secret must not appear")), "provider_error"),
    (FakeReranker(delay=.05), "timeout"), (None, "disabled"),
])
def test_provider_error_timeout_and_offline_fallback(provider, status):
    rows = rerank_rows()
    result, metadata = asyncio.run(rerank(rows, provider, MatchingConfig(rerank_timeout_seconds=.001)))
    assert result == rows and metadata.status == status


def test_rerank_boundary_and_injected_structured_client():
    class Client:
        async def complete_json(self, system, user):
            assert len(json.loads(user)) == 2
            assert "two-sentence" in system
            return valid_output()
    rows = rerank_rows()
    assert asyncio.run(rerank(rows, StructuredReranker(Client())))[1].status == "applied"
    with pytest.raises(ValueError):
        asyncio.run(rerank(rows * 3, FakeReranker()))
