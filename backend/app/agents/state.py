from typing import Any, Literal, TypedDict

AgentIntent = Literal["safety", "matches", "profile", "conversation", "general"]


class AgentState(TypedDict, total=False):
    user_id: int
    session_id: str
    message: str
    intent: AgentIntent
    profile: dict[str, Any]
    memory: list[dict[str, str]]
    tool_result: dict[str, Any]
    response: str
    provider: str

