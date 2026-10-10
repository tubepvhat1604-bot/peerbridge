from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid5

from ..agents.moderator import ChatTurn, ModeratorInput, ModeratorOutput, moderate_message
from ..agents.moderator.socratic import SocraticSession
from ..enums import ModerationAction
from ..schemas import ModerationResult

ModerationContext = Mapping[str, Any]
ModerateMessage = Callable[[ModeratorInput], Awaitable[ModeratorOutput]]
DEFAULT_COURSE_ID = "demo-course"
_ID_NAMESPACE = uuid5(NAMESPACE_URL, "dong-dieu-backend-moderation")


@runtime_checkable
class ModerationAgentProtocol(Protocol):
    async def moderate(
        self,
        session_id: str,
        message: str,
        context: ModerationContext,
    ) -> ModerationResult:
        """Moderate a study-session message before it reaches learners."""
        ...


class MockModerationAgent:
    def __init__(self, result: ModerationResult | None = None) -> None:
        self._result = result

    async def moderate(
        self,
        session_id: str,
        message: str,
        context: ModerationContext,
    ) -> ModerationResult:
        if self._result is not None:
            return self._result
        return ModerationResult(
            action=ModerationAction.ALLOW,
            risk_score=0.0,
            reason="mock moderation",
            guidance=None,
            needs_human_review=False,
        )


def _stable_uuid(kind: str, value: Any) -> UUID:
    text = str(value).strip()
    try:
        return UUID(text)
    except (TypeError, ValueError):
        return uuid5(_ID_NAMESPACE, f"{kind}:{text}")


def _context_value(context: ModerationContext, key: str, fallback: Any) -> Any:
    value = context.get(key)
    return fallback if value is None or value == "" else value


def _course_id(context: ModerationContext) -> str:
    value = context.get("course_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_COURSE_ID


def _to_moderator_input(session_id: str, message: str, context: ModerationContext) -> ModeratorInput:
    message_id = _context_value(context, "message_id", f"{session_id}:{message}")
    sender_id = _context_value(context, "sender_id", f"{session_id}:unknown-sender")
    return ModeratorInput(
        session_id=_stable_uuid("session", session_id),
        message_id=_stable_uuid("message", message_id),
        sender_id=_stable_uuid("sender", sender_id),
        message=message,
        course_id=_course_id(context),
        conversation_history=[ChatTurn(sender_id=_stable_uuid("sender", turn["sender_id"]), content=turn["content"])
            for turn in context.get("conversation_history", [])],
        room_topic=str(context.get("topic") or ""),
        socratic_session=SocraticSession.model_validate(context["socratic_session"])
            if context.get("socratic_session") else None,
    )


def _to_moderation_result(output: ModeratorOutput) -> ModerationResult:
    return ModerationResult(
        action=output.action,
        risk_score=output.risk_score,
        reason=output.reason,
        guidance=output.guidance,
        needs_human_review=output.needs_human_review,
        retrieved_sources=[source.model_dump(mode="json") for source in output.retrieved_sources],
        audit=output.audit,
    )


class LangGraphModerationAgent:
    def __init__(self, moderate: ModerateMessage | None = None) -> None:
        self._moderate = moderate

    async def moderate(
        self,
        session_id: str,
        message: str,
        context: ModerationContext,
    ) -> ModerationResult:
        payload = _to_moderator_input(session_id=session_id, message=message, context=context)
        output = await (self._moderate or moderate_message)(payload)
        return _to_moderation_result(output)


class SocraticModeratorService:
    def __init__(self, agent: ModerationAgentProtocol) -> None:
        self.agent = agent

    async def moderate(
        self,
        session_id: str,
        message: str,
        context: ModerationContext | None = None,
    ) -> ModerationResult:
        return await self.agent.moderate(
            session_id=session_id,
            message=message,
            context=dict(context or {}),
        )


_default_agent = LangGraphModerationAgent()


def get_moderation_agent() -> ModerationAgentProtocol:
    return _default_agent
