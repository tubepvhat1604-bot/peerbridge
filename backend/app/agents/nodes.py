from .memory import load_memory, save_turn
from .provider import generate_response
from .router import detect_intent
from .state import AgentState
from .tools import conversation_context, find_recommendations, get_profile_context, inspect_profile, safety_guidance


def load_context_node(state: AgentState) -> dict:
    return {
        "profile": get_profile_context(state["user_id"]),
        "memory": load_memory(state["user_id"], state["session_id"]),
    }


def route_intent_node(state: AgentState) -> dict:
    return {"intent": detect_intent(state["message"])}


def profile_tool_node(state: AgentState) -> dict:
    return {"tool_result": inspect_profile(state["profile"])}


def matches_tool_node(state: AgentState) -> dict:
    return {"tool_result": find_recommendations(state["user_id"], state["profile"])}


def conversation_tool_node(state: AgentState) -> dict:
    return {"tool_result": conversation_context(state["user_id"])}


def safety_tool_node(_: AgentState) -> dict:
    return {"tool_result": safety_guidance()}


def general_tool_node(_: AgentState) -> dict:
    return {"tool_result": {"capabilities": ["profile", "matches", "conversation", "safety"]}}


async def generate_response_node(state: AgentState) -> dict:
    response, provider = await generate_response(
        message=state["message"],
        intent=state["intent"],
        profile=state["profile"],
        tool_result=state["tool_result"],
        memory=state["memory"],
    )
    return {"response": response, "provider": provider}


def save_memory_node(state: AgentState) -> dict:
    save_turn(state["user_id"], state["session_id"], state["message"], state["response"])
    return {}

