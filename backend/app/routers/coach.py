from fastapi import APIRouter, Depends, Path

from ..repositories.plans import PlanError
from ..security import current_user
from ..services.coach import CoachService, get_coach_service
from .plans import http_error

router = APIRouter(prefix="/coach", tags=["coach"])


@router.get("/{pair_id}")
def list_interventions(
    pair_id: int = Path(gt=0), user=Depends(current_user), service: CoachService = Depends(get_coach_service)
):
    try:
        return {"interventions": service.list(pair_id, user)}
    except PlanError as error:
        raise http_error(error) from error


@router.post("/{pair_id}/evaluate")
async def evaluate(
    pair_id: int = Path(gt=0), user=Depends(current_user), service: CoachService = Depends(get_coach_service)
):
    try:
        return await service.evaluate(pair_id, user)
    except PlanError as error:
        raise http_error(error) from error
