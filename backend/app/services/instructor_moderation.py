import sqlite3
from collections.abc import Generator

from ..db import database, utc_now
from ..enums import Role
from ..repositories.moderation import ModerationRepository
from ..schemas import InstructorReviewRequest, ModerationEventListResponse, ModerationEventRecord


class InstructorModerationForbiddenError(Exception):
    """Raised when a non-admin tries to access moderation review APIs."""


class ModerationEventNotFoundError(Exception):
    """Raised when a moderation event does not exist."""


class ModerationEventAlreadyReviewedError(Exception):
    """Raised when a moderation event already has an instructor review."""


class InstructorModerationService:
    def __init__(self, repository: ModerationRepository) -> None:
        self.repository = repository

    def list_moderation_events(self, user: dict) -> ModerationEventListResponse:
        self._require_instructor(user)
        # Admin xem log kiểm duyệt của mọi phiên.
        items = [ModerationEventRecord(**record) for record in self.repository.list_moderation_events(None)]
        return ModerationEventListResponse(items=items, count=len(items))

    def review_moderation_event(
        self,
        user: dict,
        moderation_event_id: int,
        payload: InstructorReviewRequest,
    ) -> ModerationEventRecord:
        instructor_id = self._require_instructor(user)
        event = self.repository.get_moderation_event(moderation_event_id)
        if event is None:
            raise ModerationEventNotFoundError("Moderation event not found")
        try:
            record = self.repository.create_instructor_review(
                moderation_event_id=moderation_event_id,
                instructor_id=instructor_id,
                payload=payload,
                created_at=utc_now(),
            )
        except sqlite3.IntegrityError as error:
            raise ModerationEventAlreadyReviewedError("Moderation event already reviewed") from error
        return ModerationEventRecord(**record)

    @staticmethod
    def _require_instructor(user: dict) -> int:
        if str(user.get("role")) != Role.INSTRUCTOR.value:
            raise InstructorModerationForbiddenError("Only admins can review moderation events")
        return int(user["id"])


def get_instructor_moderation_service() -> Generator[InstructorModerationService, None, None]:
    with database() as connection:
        yield InstructorModerationService(ModerationRepository(connection))
