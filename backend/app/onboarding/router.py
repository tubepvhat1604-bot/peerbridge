from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from ..security import current_user
from .catalog import get_concept, list_concepts
from .contracts import (
    CandidateRequest,
    CandidateResponse,
    CatalogResponse,
    Concept,
    ConfirmRequest,
    Domain,
    LearnerProfile,
    OnboardingInput,
    PairProfiles,
)
from .retrieval import LocalConceptRetriever
from .service import OnboardingError, OnboardingService, get_onboarding_service

router = APIRouter(tags=["Data 1 onboarding"])


def current_student(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "STUDENT":
        raise HTTPException(status_code=403, detail="Student access required")
    return user


Service = Annotated[OnboardingService, Depends(get_onboarding_service)]
Student = Annotated[dict, Depends(current_student)]


@router.get("/concepts", response_model=CatalogResponse)
def concepts(user: Annotated[dict, Depends(current_user)], domain: Domain | None = None) -> CatalogResponse:
    return CatalogResponse(concepts=list_concepts(domain))


@router.post("/concepts/candidates", response_model=CandidateResponse)
def candidates(payload: CandidateRequest, user: Annotated[dict, Depends(current_user)]) -> CandidateResponse:
    retriever = LocalConceptRetriever()
    return CandidateResponse(backend=retriever.backend,
                             candidates=retriever.retrieve(payload.topic, payload.domain, payload.top_k))


@router.get("/concepts/{concept_id}", response_model=Concept)
def concept(concept_id: str, user: Annotated[dict, Depends(current_user)]) -> Concept:
    try:
        return get_concept(concept_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Concept not found") from error


@router.post("/profile", response_model=LearnerProfile)
async def submit_profile(payload: OnboardingInput, user: Student, service: Service) -> LearnerProfile:
    return await service.submit(int(user["id"]), payload)


@router.get("/profile", response_model=LearnerProfile)
def profile(user: Student, service: Service) -> LearnerProfile:
    try:
        return service.get_profile(int(user["id"]))
    except OnboardingError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.get("/profile/confirmed", response_model=LearnerProfile)
def confirmed_profile(user: Student, service: Service) -> LearnerProfile:
    try:
        return service.get_profile(int(user["id"]), confirmed_only=True)
    except OnboardingError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.post("/profile/confirm", response_model=LearnerProfile)
def confirm_profile(payload: ConfirmRequest, user: Student, service: Service) -> LearnerProfile:
    try:
        return service.confirm(int(user["id"]), payload)
    except OnboardingError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.get("/pairs/{pair_id}/concept-profiles", response_model=PairProfiles)
def pair_profiles(pair_id: Annotated[int, Path(gt=0)], user: Student, service: Service) -> PairProfiles:
    try:
        return service.get_pair_profiles(int(user["id"]), pair_id)
    except OnboardingError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
