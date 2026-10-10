from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from ..onboarding.router import current_student
from .contracts import Invitation, InviteRequest, MatchResponse, Pair
from .reranking import Reranker
from .service import PairError, PairService, get_pair_service, get_reranker

router = APIRouter(prefix="/pairs", tags=["Data 1 matching"])
Student = Annotated[dict, Depends(current_student)]
Service = Annotated[PairService, Depends(get_pair_service)]
Provider = Annotated[Reranker | None, Depends(get_reranker)]
PositiveID = Annotated[int, Path(gt=0)]
T = TypeVar("T")


def invoke(action: Callable[[], T]) -> T:
    try:
        return action()
    except PairError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.post("/match", response_model=MatchResponse)
async def match(user: Student, service: Service, provider: Provider) -> MatchResponse:
    service.reranker = provider
    try:
        return await service.match(user["id"])
    except PairError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.delete("/match", status_code=204)
def cancel_match(user: Student, service: Service) -> Response:
    invoke(lambda: service.cancel_matching(user["id"]))
    return Response(status_code=204)


@router.post("/invite", response_model=Invitation, status_code=201)
def invite(payload: InviteRequest, user: Student, service: Service) -> Invitation:
    return invoke(lambda: service.invite(user["id"], payload))


@router.post("/join/{code}", response_model=Pair)
def join(code: Annotated[str, Path(min_length=20, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")],
         user: Student, service: Service) -> Pair:
    return invoke(lambda: service.join(user["id"], code))


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke(invitation_id: PositiveID, user: Student, service: Service) -> Response:
    invoke(lambda: service.revoke_invitation(user["id"], invitation_id))
    return Response(status_code=204)


@router.get("/{pair_id}", response_model=Pair)
def pair(pair_id: PositiveID, user: Student, service: Service) -> Pair:
    return invoke(lambda: service.get_pair(user["id"], pair_id))


@router.post("/{pair_id}/leave", response_model=Pair)
def leave(pair_id: PositiveID, user: Student, service: Service) -> Pair:
    return invoke(lambda: service.leave(user["id"], pair_id))
