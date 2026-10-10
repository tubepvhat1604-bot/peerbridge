"""Socratic Moderator agent: điểm vào công khai cho service layer."""

from .contract import ChatTurn, ModeratorInput, ModeratorOutput, RetrievedSource
from .graph import moderate_default, warmup_moderator
from .hitl import (
    HITLQueue,
    InMemoryHITLQueue,
    InstructorReviewInput,
    ModerationEventRecord,
    moderate_message_with_event,
)


async def moderate_message(payload: ModeratorInput) -> ModeratorOutput:
    """Kiểm duyệt một tin nhắn bằng LangGraph moderator (deps theo settings, mặc định FakeLLM)."""
    return await moderate_default(payload)


__all__ = [
    "ChatTurn",
    "HITLQueue",
    "InMemoryHITLQueue",
    "InstructorReviewInput",
    "ModerationEventRecord",
    "ModeratorInput",
    "ModeratorOutput",
    "RetrievedSource",
    "moderate_message",
    "moderate_message_with_event",
    "warmup_moderator",
]
