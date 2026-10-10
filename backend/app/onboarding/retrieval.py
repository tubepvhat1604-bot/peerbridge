import re
import unicodedata
from typing import Protocol

from .catalog import get_concept, list_concepts
from .contracts import Candidate, Domain


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold()).replace("đ", "d")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def phrase_present(phrase: str, text: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {text} "


class ConceptRetriever(Protocol):
    backend: str

    def retrieve(self, topic: str, domain: Domain, top_k: int = 5) -> list[Candidate]: ...


class LocalConceptRetriever:
    """Offline alias/lexical retrieval; scores are heuristics, not embedding probabilities."""

    backend = "local_lexical"

    def retrieve(self, topic: str, domain: Domain, top_k: int = 5) -> list[Candidate]:
        if not 1 <= top_k <= 5:
            raise ValueError("top_k must be between 1 and 5")
        normalized = normalize_text(topic)
        terms = set(normalized.split())
        candidates: list[Candidate] = []
        matched_aliases: dict[str, list[str]] = {}
        for concept in list_concepts(domain):
            aliases = [normalize_text(alias) for alias in [concept.id, concept.name, *concept.aliases]]
            matched_aliases[concept.id] = [alias for alias in aliases if phrase_present(alias, normalized)]
            if normalized in aliases:
                score = 1.0
            elif any(phrase_present(alias, normalized) for alias in aliases):
                score = 0.9
            else:
                concept_terms = set(normalize_text(concept.name + " " + concept.description).split())
                score = 0.45 * len(terms & concept_terms) / max(1, len(terms | concept_terms))
            if score > 0:
                candidates.append(Candidate(
                    concept_id=concept.id, domain=concept.domain, name=concept.name,
                    description=concept.description, score=round(score, 6),
                ))
        # "LEFT JOIN" is more specific than the embedded "JOIN". Keep JOIN if it also occurs separately.
        def has_independent_alias(candidate: Candidate) -> bool:
            aliases = matched_aliases[candidate.concept_id]
            if not aliases:
                return True
            for alias in aliases:
                remaining = f" {normalized} "
                longer_aliases = {
                    other_alias for other_id, others in matched_aliases.items() if other_id != candidate.concept_id
                    for other_alias in others if other_alias != alias and phrase_present(alias, other_alias)
                }
                for longer in sorted(longer_aliases, key=lambda value: (-len(value), value)):
                    remaining = remaining.replace(f" {longer} ", " ")
                if phrase_present(alias, remaining):
                    return True
            return False

        candidates = [candidate for candidate in candidates if has_independent_alias(candidate)]
        return sorted(candidates, key=lambda item: (-item.score, item.concept_id))[:top_k]


def validate_candidates(candidates: list[Candidate], domain: Domain, top_k: int = 5) -> list[Candidate]:
    if len(candidates) > top_k:
        raise ValueError("Retriever returned too many candidates")
    validated: list[Candidate] = []
    seen: set[str] = set()
    for item in candidates:
        candidate = Candidate.model_validate(item)
        concept = get_concept(candidate.concept_id)
        if concept.domain != domain or candidate.domain != domain or concept.id in seen:
            raise ValueError("Retriever returned duplicate or cross-domain candidates")
        seen.add(concept.id)
        # Canonical text wins over text provided by an external retrieval adapter.
        validated.append(candidate.model_copy(update={"name": concept.name, "description": concept.description}))
    return sorted(validated, key=lambda item: (-item.score, item.concept_id))


def infer_domain(topic: str) -> Domain | None:
    text = normalize_text(topic)
    domains: set[Domain] = set()
    if phrase_present("sql", text):
        domains.add("sql")
    if phrase_present("python", text) or phrase_present("py", text):
        domains.add("python")
    if len(domains) == 1:
        return next(iter(domains))
    if domains:
        return None
    for concept in list_concepts():
        if any(phrase_present(normalize_text(alias), text) for alias in [concept.id, *concept.aliases]):
            domains.add(concept.domain)
    return next(iter(domains)) if len(domains) == 1 else None
