import json
from functools import lru_cache
from pathlib import Path

from .contracts import CATALOG_VERSION, Concept, Domain

CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "concepts" / "catalog.json"


def validate_catalog(concepts: tuple[Concept, ...]) -> None:
    by_id = {concept.id: concept for concept in concepts}
    if len(by_id) != len(concepts):
        raise ValueError("Duplicate concept ID")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(concept_id: str) -> None:
        if concept_id in visiting:
            raise ValueError("Concept prerequisite cycle")
        if concept_id in visited:
            return
        visiting.add(concept_id)
        concept = by_id[concept_id]
        for prerequisite in concept.prerequisites:
            if prerequisite not in by_id or by_id[prerequisite].domain != concept.domain:
                raise ValueError(f"Unknown or cross-domain prerequisite: {prerequisite}")
            visit(prerequisite)
        visiting.remove(concept_id)
        visited.add(concept_id)

    for concept in concepts:
        visit(concept.id)


@lru_cache
def load_catalog() -> tuple[Concept, ...]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data["catalog_version"] != CATALOG_VERSION:
        raise ValueError("Catalog version does not match contract")
    concepts = tuple(Concept.model_validate(item) for item in data["concepts"])
    validate_catalog(concepts)
    return concepts


def get_concept(concept_id: str) -> Concept:
    for concept in load_catalog():
        if concept.id == concept_id:
            return concept.model_copy(deep=True)
    raise ValueError(f"Unknown concept ID: {concept_id}")


def list_concepts(domain: Domain | None = None) -> list[Concept]:
    return [concept.model_copy(deep=True) for concept in load_catalog() if domain is None or concept.domain == domain]
