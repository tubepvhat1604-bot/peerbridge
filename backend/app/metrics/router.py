import hmac
from collections.abc import Callable
from datetime import date
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query

from ..config import get_settings
from ..onboarding.router import current_student
from .adapters import InputUnavailableError
from .contracts import DailyJobRequest, DailyJobResult, MetricHistory, MetricView
from .service import MeasurementService, MetricError, get_measurement_service

router = APIRouter(prefix="/pairs", tags=["Data 1 measurement"])
jobs_router = APIRouter(prefix="/jobs", tags=["Internal measurement jobs"])
Student = Annotated[dict, Depends(current_student)]
Service = Annotated[MeasurementService, Depends(get_measurement_service)]
PositiveID = Annotated[int, Path(gt=0)]
T = TypeVar("T")


def invoke(action: Callable[[], T]) -> T:
    try:
        return action()
    except MetricError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except InputUnavailableError as error:
        raise HTTPException(status_code=503, detail="Authoritative measurement inputs are unavailable") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid measurement input") from error


def authorize_job(x_job_secret: Annotated[str | None, Header(max_length=512)] = None) -> None:
    configured = get_settings().daily_metrics_job_secret
    if configured is None or not configured.get_secret_value():
        raise HTTPException(status_code=503, detail="Daily metrics job is not configured")
    if x_job_secret is None or not hmac.compare_digest(x_job_secret.encode(), configured.get_secret_value().encode()):
        raise HTTPException(status_code=401, detail="Invalid job authorization")


@jobs_router.post("/daily-metrics", response_model=DailyJobResult, dependencies=[Depends(authorize_job)])
def daily_metrics(service: Service, request: DailyJobRequest = DailyJobRequest()) -> DailyJobResult:
    return invoke(lambda: service.daily(request))


@router.get("/{pair_id}/metrics", response_model=MetricView)
def current_metrics(pair_id: PositiveID, user: Student, service: Service) -> MetricView:
    invoke(lambda: service.authorize(pair_id, user["id"]))
    return MetricView.from_metrics(invoke(lambda: service.current(pair_id)))


@router.get("/{pair_id}/metrics/history", response_model=MetricHistory)
def history(pair_id: PositiveID, user: Student, service: Service,
            limit: Annotated[int, Query(ge=1, le=90)] = 30, before: date | None = None) -> MetricHistory:
    invoke(lambda: service.authorize(pair_id, user["id"]))
    records = invoke(lambda: service.repository.history(service.repository.context(pair_id), limit, before))
    return MetricHistory(pair_id=pair_id, items=[MetricView.from_metrics(record) for record in records])


@router.post("/{pair_id}/metrics/refresh", response_model=MetricView)
def refresh(pair_id: PositiveID, user: Student, service: Service) -> MetricView:
    invoke(lambda: service.authorize(pair_id, user["id"]))
    metrics, _ = invoke(lambda: service.recompute(pair_id))
    return MetricView.from_metrics(metrics)
