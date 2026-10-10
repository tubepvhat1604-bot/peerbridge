from ..onboarding.catalog import get_concept
from .contracts import ExplanationFacts, MatchLevel

LEVEL_LABELS = {"complementary": "Complementary", "same_outcome": "Same outcome",
                "concept_overlap": "Concept overlap", "shared_commitment": "Shared commitment only"}


def explain(facts: ExplanationFacts, level: MatchLevel) -> str:
    def names(ids: list[str]) -> str:
        return ", ".join(get_concept(concept_id).name for concept_id in ids)
    if facts.concepts_a_receives_from_b and facts.concepts_b_receives_from_a:
        skill = (f"your partner offers {names(facts.concepts_a_receives_from_b)} that you need, "
                 f"and you offer {names(facts.concepts_b_receives_from_a)} that they need")
    elif facts.same_stated_goal:
        skill = "you confirmed the same stated learning goal"
    elif facts.shared_learning_concepts:
        skill = f"you are both learning {names(facts.shared_learning_concepts)}"
    else:
        skill = "no reciprocal concept coverage or shared learning concepts are confirmed"
    # Exactly two authored sentences. Never use untrusted prose or behavioral traits in public explanations.
    schedule = (f"You share {len(facts.common_slots)} weekly study slots in the reference week "
                f"and committed {facts.weekly_hours_a:g} and {facts.weekly_hours_b:g} hours per week")
    if facts.deadline_difference_days is not None:
        schedule += f", with deadlines {facts.deadline_difference_days} days apart"
    return f"{LEVEL_LABELS[level]}: {skill}. {schedule}."
