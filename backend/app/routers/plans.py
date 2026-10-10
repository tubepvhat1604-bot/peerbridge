import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..agents.plan_coach.contract import AcceptRequest, CompletionEvent, GenerateRequest, ReplanRequest
from ..agents.plan_coach.llm import PlannerFailureError
from ..agents.plan_coach.scheduler import PlanValidationError
from ..repositories.plans import PlanError
from ..security import current_user
from ..services.plans import PlanService, get_plan_service

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=280)


@router.get("/{pair_id}/notes")
def read_notes(pair_id: int = Path(gt=0), user=Depends(current_user)):
    from ..services.plan_notes import notes
    try:
        return notes(pair_id,user)
    except PlanError as error:
        raise http_error(error) from error


@router.post("/{pair_id}/notes", status_code=201)
def add_note(body: PlanNoteIn, pair_id: int = Path(gt=0), user=Depends(current_user)):
    from ..services.plan_notes import notes
    try:
        return notes(pair_id,user,body.text)
    except PlanError as error:
        raise http_error(error) from error


@router.get("/{pair_id}/commitments")
def commitments(pair_id: int = Path(gt=0), user=Depends(current_user)):
    from ..services.commitments import plan_commitments
    try:
        return plan_commitments(pair_id, user)
    except PlanError as error:
        raise http_error(error) from error


@router.post("/{pair_id}/commit")
def commit(pair_id: int = Path(gt=0), user=Depends(current_user)):
    from ..services.commitments import plan_commitments
    try:
        return plan_commitments(pair_id, user, commit=True)
    except PlanError as error:
        raise http_error(error) from error


def http_error(error):
    if isinstance(error, PlanError):
        return HTTPException(error.status, detail=f"{error.code}: {error.message}")
    if isinstance(error, PlanValidationError):
        return HTTPException(422, detail="; ".join(f"{i.code}: {i.message}" for i in error.issues))
    raise error


@router.get("/{pair_id}/setup")
def setup(pair_id: int = Path(gt=0), user=Depends(current_user), service: PlanService = Depends(get_plan_service)):
    try:
        return service.setup(pair_id, user)
    except (PlanError, PlanValidationError) as error:
        raise http_error(error) from error


@router.post("/generate", status_code=201)
async def generate(
    payload: GenerateRequest,
    user=Depends(current_user),
    service: PlanService = Depends(get_plan_service),
    idempotency_key: str = Header(min_length=1, max_length=120),
):
    try:
        return await service.generate(payload, user, idempotency_key)
    except PlannerFailureError as error:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Không lập được kế hoạch hợp lệ sau hai lần sửa; chưa lưu kế hoạch. "
                + "; ".join(f"{i.code}: {i.message}" for i in error.issues),
                "trace_id": error.trace_id,
                "errors": [i.model_dump(mode="json") for i in error.issues],
                "unplanned_concepts": error.trace["unplanned_concepts"],
            },
        )
    except (PlanError, PlanValidationError) as error:
        raise http_error(error) from error


@router.get("/{pair_id}/traces")
def traces(pair_id: int = Path(gt=0), user=Depends(current_user), service: PlanService = Depends(get_plan_service)):
    try:
        return service.traces(pair_id, user)
    except PlanError as error:
        raise http_error(error) from error


@router.get("/{pair_id}")
def read(pair_id: int = Path(gt=0), user=Depends(current_user), service: PlanService = Depends(get_plan_service)):
    try:
        return service.read(pair_id, user)
    except (PlanError, PlanValidationError) as error:
        raise http_error(error) from error


@router.post("/{pair_id}/replan", status_code=201)
def replan(
    payload: ReplanRequest,
    pair_id: int = Path(gt=0),
    user=Depends(current_user),
    service: PlanService = Depends(get_plan_service),
):
    try:
        return service.replan(pair_id, user, payload)
    except (PlanError, PlanValidationError) as error:
        raise http_error(error) from error


@router.post("/{pair_id}/proposals/{proposal_id}/{decision}")
def decide(
    payload: AcceptRequest,
    decision: str,
    pair_id: int = Path(gt=0),
    proposal_id: int = Path(gt=0),
    user=Depends(current_user),
    service: PlanService = Depends(get_plan_service),
):
    if decision not in ("accept", "reject"):
        raise HTTPException(404, "Unknown decision")
    try:
        return service.decide_proposal(pair_id, proposal_id, user, payload.expected_version, decision == "accept")
    except (PlanError, PlanValidationError) as error:
        raise http_error(error) from error


@router.post("/events/completion")
def completion(
    payload: CompletionEvent, service: PlanService = Depends(get_plan_service), x_vision_key: str = Header(default="")
):
    key = service.settings.vision_adapter_key.get_secret_value()
    if not key:
        raise HTTPException(503, "AI Vision adapter chưa được cấu hình")
    if not secrets.compare_digest(key, x_vision_key):
        raise HTTPException(403, "AI Vision adapter authentication required")
    try:
        return service.complete(payload)
    except (PlanError, PlanValidationError) as error:
        raise http_error(error) from error


class ScheduleEditIn(BaseModel):
    expected_version: int = Field(gt=0)
    scheduled_start: datetime
    minutes: int = Field(ge=30, le=90)


@router.patch("/{pair_id}/items/{item_id}/schedule")
def edit_schedule(payload: ScheduleEditIn, item_id: str, pair_id: int = Path(gt=0), user=Depends(current_user), service: PlanService = Depends(get_plan_service)):
    try:
        return service.edit_schedule(pair_id, user, item_id, payload)
    except PlanError as error:
        raise http_error(error) from error
