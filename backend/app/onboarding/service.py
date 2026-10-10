from collections.abc import Generator

from ..db import database, utc_now
from .catalog import get_concept
from .contracts import ConfirmRequest, LearnerProfile, OnboardingInput, PairProfiles, UserConceptInput
from .extraction import LocalProfileExtractor, ProfileExtractor
from .normalization import ConceptNormalizer
from .repository import OnboardingRepository


class OnboardingError(Exception):
    def __init__(self, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.status_code = status_code


class OnboardingService:
    def __init__(self, repository: OnboardingRepository, normalizer: ConceptNormalizer | None = None,
                 extractor: ProfileExtractor | None = None) -> None:
        self.repository = repository
        self.normalizer = normalizer or ConceptNormalizer()
        self.extractor = extractor or LocalProfileExtractor()

    async def submit(self, user_id: int, payload: OnboardingInput) -> LearnerProfile:
        extracted = await self.extractor.extract(payload)
        extracted = OnboardingInput.model_validate(extracted)
        mappings = [await self.normalizer.normalize(topic, index) for index, topic in enumerate(extracted.topics)]
        return self.repository.save_draft(user_id, extracted, mappings, utc_now())

    def get_profile(self, user_id: int, *, confirmed_only: bool = False) -> LearnerProfile:
        profile = self.repository.get_profile(user_id)
        if profile is None:
            raise OnboardingError("Learner concept profile not found", 404)
        if confirmed_only and profile.status != "confirmed":
            raise OnboardingError("Learner concept profile requires confirmation", 409)
        return profile

    def confirm(self, user_id: int, request: ConfirmRequest) -> LearnerProfile:
        profile = self.get_profile(user_id)
        if profile.revision != request.revision or profile.status != "draft":
            raise OnboardingError("Profile changed; reload before confirming", 409)
        indices = [item.topic_index for item in request.selections]
        if len(indices) != len(set(indices)) or set(indices) != set(range(len(profile.mappings))):
            raise OnboardingError("Review every topic exactly once")
        selected: dict[tuple[str, str], UserConceptInput] = {}
        mappings = [item.model_copy(deep=True) for item in profile.mappings]

        def add_concept(item: UserConceptInput) -> None:
            get_concept(item.concept_id)
            key = (item.concept_id, item.role)
            if any(previous.concept_id == item.concept_id and previous.self_level != item.self_level
                   for previous in selected.values()):
                raise ValueError("Conflicting levels for the same concept")
            selected[key] = item

        try:
            for selection in request.selections:
                mapping = mappings[selection.topic_index]
                level = selection.self_level or mapping.topic.self_level
                mapping.topic = mapping.topic.model_copy(update={"self_level": level})
                mapping.concept_id = selection.concept_id
                mapping.reason = "user_confirmed" if selection.concept_id else "user_unmapped"
                # Confidence remains the machine estimate; confirmation is represented by status/reason.
                if selection.concept_id is not None:
                    concept = get_concept(selection.concept_id)
                    if mapping.topic.domain is not None and concept.domain != mapping.topic.domain:
                        raise ValueError("Correction must respect the explicitly supplied domain")
                    mapping.resolved_domain = concept.domain
                    add_concept(UserConceptInput(concept_id=concept.id, role=mapping.topic.role, self_level=level))
            for item in request.additional_concepts:
                add_concept(item)
            return self.repository.confirm(profile, list(selected.values()), mappings, utc_now())
        except ValueError as error:
            if str(error) == "stale_revision":
                raise OnboardingError("Profile changed; reload before confirming", 409) from error
            raise OnboardingError(str(error)) from error

    def get_pair_profiles(self, requesting_user_id: int, pair_id: int) -> PairProfiles:
        row = self.repository.connection.execute(
            "SELECT user_a_id, user_b_id FROM peer_matches WHERE id=?", (pair_id,),
        ).fetchone()
        if row is None:
            raise OnboardingError("Pair not found", 404)
        if requesting_user_id not in (row["user_a_id"], row["user_b_id"]):
            raise OnboardingError("Pair membership required", 403)
        return PairProfiles(pair_id=pair_id,
                            user_a=self.get_profile(row["user_a_id"], confirmed_only=True),
                            user_b=self.get_profile(row["user_b_id"], confirmed_only=True))


def get_onboarding_service() -> Generator[OnboardingService, None, None]:
    with database() as connection:
        yield OnboardingService(OnboardingRepository(connection))
