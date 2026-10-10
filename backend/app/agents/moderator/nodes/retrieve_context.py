"""Node retrieve_context: lấy tài liệu môn học liên quan cho nhánh GUIDE."""

from ..retriever import Retriever
from ..state import ModeratorState


def build_query(state: ModeratorState) -> str:
    """Anchor follow-up messages to the original learning task and room context."""
    payload = state["input"]
    session = payload.socratic_session
    if session:
        parts = [session.original_question, session.topic or payload.room_topic]
        parts.extend(turn.content[:300] for turn in payload.conversation_history[-3:])
        parts.append(payload.message)
        return "\n".join(part for part in parts if part)[:2000]
    if payload.room_topic:
        return f"{payload.room_topic}\n{payload.message}"[:2000]
    if payload.conversation_history:
        return f"{payload.message}\n{payload.conversation_history[-1].content}"
    return payload.message


async def retrieve_context(state: ModeratorState, retriever: Retriever, top_k: int, default_course_id: str = "") -> dict:
    """Trả retrieved_sources (rỗng nếu retriever lỗi, lỗi ghi vào errors).

    Phòng chưa được gán khoá thì dùng default_course_id (tài liệu chung của cả lớp); trống thì không tra.
    """
    errors = list(state.get("errors", []))
    course_id = state["input"].course_id
    if course_id == "__no_authorized_course__":
        if not default_course_id:
            return {"retrieved_sources": [], "errors": errors}
        course_id = default_course_id
    try:
        sources = await retriever.search(build_query(state), course_id, top_k)
    except Exception as exc:  # noqa: BLE001 - RAG lỗi thì dùng template
        errors.append(f"retrieve_context: {type(exc).__name__}: {exc}")
        sources = []
    return {"retrieved_sources": sources, "errors": errors}
