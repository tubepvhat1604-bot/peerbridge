from fastapi import APIRouter, Depends, HTTPException, Path

from ..schemas import StudySessionCreateRequest, StudySessionListResponse, StudySessionResponse
from ..security import current_user
from ..services.sessions import (
    StudySessionForbiddenError,
    StudySessionNotFoundError,
    StudySessionOwnershipError,
    StudySessionService,
    get_study_session_service,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_http_error(error: Exception) -> HTTPException:
    if isinstance(error, StudySessionNotFoundError):
        return HTTPException(status_code=404, detail="Study session not found")
    if isinstance(error, (StudySessionForbiddenError, StudySessionOwnershipError)):
        return HTTPException(status_code=403, detail="Study session access denied")
    return HTTPException(status_code=500, detail="Could not process study session")


@router.get("", response_model=StudySessionListResponse)
def list_study_sessions(
    user: dict = Depends(current_user),
    service: StudySessionService = Depends(get_study_session_service),
) -> StudySessionListResponse:
    try:
        return service.list_study_sessions(user)
    except StudySessionForbiddenError as error:
        raise _session_http_error(error) from error


@router.post("", response_model=StudySessionResponse, status_code=201)
def create_study_session(
    payload: StudySessionCreateRequest,
    user: dict = Depends(current_user),
    service: StudySessionService = Depends(get_study_session_service),
) -> StudySessionResponse:
    try:
        return service.create_study_session(user, payload)
    except (StudySessionForbiddenError, StudySessionNotFoundError, StudySessionOwnershipError) as error:
        raise _session_http_error(error) from error


@router.get("/{session_id}", response_model=StudySessionResponse)
def get_study_session(
    session_id: int = Path(gt=0),
    user: dict = Depends(current_user),
    service: StudySessionService = Depends(get_study_session_service),
) -> StudySessionResponse:
    try:
        return service.get_study_session(user, session_id)
    except (StudySessionForbiddenError, StudySessionNotFoundError) as error:
        raise _session_http_error(error) from error
