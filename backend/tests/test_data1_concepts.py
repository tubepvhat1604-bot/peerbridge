import asyncio
import json
from pathlib import Path

import httpx
import pytest
from app.onboarding.catalog import get_concept, list_concepts, validate_catalog
from app.onboarding.contracts import INITIAL_THETA, Candidate, Concept, LearnerProfile, OnboardingInput, TopicInput
from app.onboarding.extraction import LocalProfileExtractor, StructuredProfileExtractor
from app.onboarding.normalization import ConceptNormalizer, StructuredConceptSelector
from app.onboarding.retrieval import LocalConceptRetriever, infer_domain, normalize_text, validate_candidates
from pydantic import ValidationError

CASES_PATH = Path(__file__).resolve().parents[2] / "eval" / "concept" / "phase1_cases.jsonl"
CASES = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line]


def run(coroutine):
    return asyncio.run(coroutine)


class JsonStub:
    def __init__(self, result):
        self.result = result

    async def complete_json(self, system, user):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_catalog_has_two_domains_stable_ids_and_valid_prerequisites():
    concepts = tuple(list_concepts())
    assert len(list_concepts("sql")) == len(list_concepts("python")) == 30
    assert len({item.id for item in concepts}) == 75  # 30 SQL + 30 Python + 15 bài AICB
    validate_catalog(concepts)
    assert get_concept("sql.join").domain == "sql"
    assert get_concept("py.basic").domain == "python"
    assert all(item.description and item.aliases for item in concepts)
    with pytest.raises(ValueError):
        get_concept("sql.invented")


def test_synthetic_teammate_profiles_match_versioned_contract_and_canonical_ids():
    path = CASES_PATH.parent / "confirmed_profiles.json"
    profiles = [LearnerProfile.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]
    assert len(profiles) == 5
    for profile in profiles:
        assert profile.status == "confirmed" and profile.confirmed_at
        for item in profile.user_concepts:
            assert get_concept(item.concept_id)
            assert item.theta == INITIAL_THETA[item.self_level]
            assert item.user_id == profile.user_id
    assert profiles[-1].unmapped and not profiles[-1].user_concepts


def test_catalog_rejects_cycles_missing_prerequisites_and_duplicate_ids():
    a = Concept(id="sql.a", domain="sql", name="A", description="A", prerequisites=["sql.b"])
    b = Concept(id="sql.b", domain="sql", name="B", description="B", prerequisites=["sql.a"])
    with pytest.raises(ValueError, match="cycle"):
        validate_catalog((a, b))
    with pytest.raises(ValueError, match="Unknown"):
        validate_catalog((a,))
    with pytest.raises(ValueError, match="Duplicate"):
        validate_catalog((a, a))
    with pytest.raises(ValidationError):
        Concept(id="py.bad", domain="sql", name="A", description="A")


@pytest.mark.parametrize("case", CASES, ids=[case["topic"] for case in CASES])
def test_labeled_mapping_cases(case):
    mapped = run(ConceptNormalizer().normalize(TopicInput(text=case["topic"], domain=case["domain"]), 0))
    assert mapped.concept_id == case["expected"]
    assert len(mapped.candidates) <= 5
    assert all(item.domain == case["domain"] for item in mapped.candidates)


def test_candidate_contract_is_domain_scoped_bounded_and_deterministic():
    retriever = LocalConceptRetriever()
    first = retriever.retrieve("học nối bảng", "sql")
    assert first == retriever.retrieve("học nối bảng", "sql")
    assert first[0].concept_id == "sql.join"
    assert len(first) <= 5
    with pytest.raises(ValueError):
        retriever.retrieve("JOIN", "sql", 6)
    invalid = Candidate(concept_id="py.basic", domain="sql", name="Spoof", description="Spoof", score=1)
    with pytest.raises(ValueError):
        validate_candidates([invalid], "sql")
    actual = first[0].model_copy(update={"name": "Spoof"})
    assert validate_candidates([actual], "sql")[0].name == get_concept(actual.concept_id).name


def test_domain_inference_and_text_normalization_are_conservative():
    assert normalize_text("  NỐI   BẢNG ") == "noi bang"
    assert infer_domain("học SQL JOIN") == "sql"
    assert infer_domain("Python dictionaries") == "python"
    assert infer_domain("SQL and Python") is None
    assert infer_domain("IELTS") is None
    assert run(ConceptNormalizer().normalize(TopicInput(text="IELTS"), 0)).concept_id is None


@pytest.mark.parametrize("level,theta", [("unknown", -1), ("learning", 0), ("strong", 1)])
def test_initial_theta_mapping_matches_context(level, theta):
    assert INITIAL_THETA[TopicInput(text="JOIN", self_level=level).self_level] == theta


@pytest.mark.parametrize("level,expected", [("chưa biết", "unknown"), ("đang học", "learning"), ("vững", "strong")])
def test_vietnamese_level_input(level, expected):
    assert TopicInput(text="JOIN", self_level=level).self_level == expected


@pytest.mark.parametrize("result", [
    {"concept_id": "sql.made_up", "confidence": 1, "reason": "invented"},
    {"concept_id": "py.basic", "confidence": 1, "reason": "wrong domain"},
    {"concept_id": "sql.select_basic", "confidence": 1, "reason": "outside candidates"},
    {"invalid": True},
    RuntimeError("offline client unavailable"),
    httpx.ConnectError("offline network unavailable"),
])
def test_structured_selector_failure_uses_safe_labeled_local_fallback(result):
    normalizer = ConceptNormalizer(selector=StructuredConceptSelector(JsonStub(result)))
    mapped = run(normalizer.normalize(TopicInput(text="JOIN", domain="sql"), 0))
    assert mapped.concept_id == "sql.join"
    assert mapped.backend.endswith(":fallback")


@pytest.mark.parametrize("choice,confidence", [(None, 1), ("sql.join", 0.5)])
def test_structured_selector_can_abstain_and_low_confidence_needs_review(choice, confidence):
    selector = StructuredConceptSelector(JsonStub({"concept_id": choice, "confidence": confidence, "reason": "uncertain"}))
    mapped = run(ConceptNormalizer(selector=selector).normalize(TopicInput(text="JOIN", domain="sql"), 0))
    assert mapped.concept_id is None


def test_injected_retriever_is_validated_and_falls_back_without_cross_domain_ids():
    class BadRetriever:
        backend = "broken_vector_adapter"

        def retrieve(self, topic, domain, top_k=5):
            return [Candidate(concept_id="py.basic", domain="python", name="Python", description="Python", score=1)]

    mapped = run(ConceptNormalizer(retriever=BadRetriever()).normalize(TopicInput(text="JOIN", domain="sql"), 0))
    assert mapped.concept_id == "sql.join"
    assert mapped.backend.endswith(":fallback")


def test_goal_only_extraction_preserves_metadata_and_unrelated_goal():
    payload = OnboardingInput(learning_goal="IELTS writing", committed_weekly_hours=5, conscientiousness=0.8)
    local = run(LocalProfileExtractor().extract(payload))
    assert local.topics[0].text == payload.learning_goal
    assert local.conscientiousness == 0.8
    extracted = run(StructuredProfileExtractor(JsonStub({"topics": [
        {"text": "JOIN", "domain": "sql", "role": "need", "self_level": "unknown"},
    ]})).extract(payload))
    assert extracted.topics[0].text == "JOIN"
    assert extracted.committed_weekly_hours == 5
    assert extracted.learning_goal == payload.learning_goal
    failed = run(StructuredProfileExtractor(JsonStub({"user_id": 99})).extract(payload))
    assert failed == local


def test_structured_extraction_never_overwrites_explicit_topics_and_network_failure_is_local():
    payload = OnboardingInput(learning_goal="SQL JOIN", committed_weekly_hours=5)
    failed = run(StructuredProfileExtractor(JsonStub(httpx.ConnectError("offline"))).extract(payload))
    assert failed.topics[0].text == "SQL JOIN"
    explicit = payload.model_copy(update={"topics": [TopicInput(text="IELTS writing")]})
    assert run(StructuredProfileExtractor(JsonStub(RuntimeError("must not be called"))).extract(explicit)) == explicit


@pytest.mark.parametrize("changes", [
    {"committed_weekly_hours": 0}, {"committed_weekly_hours": float("nan")},
    {"conscientiousness": 1.1}, {"procrastination": -1}, {"timezone": "Invalid/Timezone"},
    {"learning_goal": "   "},
])
def test_invalid_onboarding_fields_are_rejected(changes):
    with pytest.raises(ValidationError):
        OnboardingInput.model_validate({"learning_goal": "SQL", "committed_weekly_hours": 5, **changes})
