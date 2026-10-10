from fastapi import APIRouter, Depends, HTTPException, Path

from ..db import database
from ..enums import ModerationAction, ReviewAction
from ..schemas import InstructorReviewRequest, ModerationEventListResponse, ModerationEventRecord
from ..security import current_user
from ..services.instructor_moderation import (
    InstructorModerationForbiddenError,
    InstructorModerationService,
    ModerationEventAlreadyReviewedError,
    ModerationEventNotFoundError,
    get_instructor_moderation_service,
)
from ..services.study_room import StudyRoomService, study_room_connections

router = APIRouter(prefix="/instructor/moderation", tags=["instructor-moderation"])


def _moderation_http_error(error: Exception) -> HTTPException:
    if isinstance(error, InstructorModerationForbiddenError):
        return HTTPException(status_code=403, detail="Chỉ Admin mới xem được log kiểm duyệt")
    if isinstance(error, ModerationEventNotFoundError):
        return HTTPException(status_code=404, detail="Moderation event not found")
    if isinstance(error, ModerationEventAlreadyReviewedError):
        return HTTPException(status_code=409, detail="Moderation event already reviewed")
    return HTTPException(status_code=500, detail="Could not process moderation review")


@router.get("", response_model=ModerationEventListResponse)
def list_instructor_moderation_events(
    user: dict = Depends(current_user),
    service: InstructorModerationService = Depends(get_instructor_moderation_service),
) -> ModerationEventListResponse:
    try:
        return service.list_moderation_events(user)
    except InstructorModerationForbiddenError as error:
        raise _moderation_http_error(error) from error


@router.post("/{moderation_event_id}/review", response_model=ModerationEventRecord, status_code=201)
async def review_moderation_event(
    payload: InstructorReviewRequest,
    moderation_event_id: int = Path(gt=0),
    user: dict = Depends(current_user),
    service: InstructorModerationService = Depends(get_instructor_moderation_service),
) -> ModerationEventRecord:
    try:
        record = service.review_moderation_event(user, moderation_event_id, payload)
        # Commit the unique review before any irreversible broadcast.
        service.repository.connection.commit()
        if payload.action == ReviewAction.INTERVENE and payload.notes.strip():
            # Admin can thiệp: lời nhắn hiện ngay trong phòng học của hai bạn.
            await study_room_connections.broadcast(record.session_id,
                StudyRoomService.admin_note_event(record.session_id, payload.notes.strip(), record.message_id))
        if payload.action == ReviewAction.OVERRIDE and payload.override_action in {ModerationAction.ALLOW, ModerationAction.GUIDE}:
            with database() as connection:
                row = connection.execute(
                    "SELECT id, session_id, sender_id, content, created_at FROM chat_messages WHERE id = ?",
                    (record.message_id,),
                ).fetchone()
            if row is not None and record.agent_action not in {ModerationAction.ALLOW, ModerationAction.GUIDE}:
                await study_room_connections.broadcast(record.session_id,
                    StudyRoomService.chat_message_event(record.session_id, dict(row)))
        return record
    except (
        InstructorModerationForbiddenError,
        ModerationEventAlreadyReviewedError,
        ModerationEventNotFoundError,
    ) as error:
        raise _moderation_http_error(error) from error
