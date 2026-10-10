from langgraph.graph import END, START, StateGraph

from .nodes import (
    conversation_tool_node,
    general_tool_node,
    generate_response_node,
    load_context_node,
    matches_tool_node,
    profile_tool_node,
    route_intent_node,
    safety_tool_node,
    save_memory_node,
)
from .state import AgentState


def _selected_tool(state: AgentState) -> str:
    return state["intent"]


builder = StateGraph(AgentState)
builder.add_node("load_context", load_context_node)
builder.add_node("route_intent", route_intent_node)
builder.add_node("profile_tool", profile_tool_node)
builder.add_node("matches_tool", matches_tool_node)
builder.add_node("conversation_tool", conversation_tool_node)
builder.add_node("safety_tool", safety_tool_node)
builder.add_node("general_tool", general_tool_node)
builder.add_node("generate_response", generate_response_node)
builder.add_node("save_memory", save_memory_node)

builder.add_edge(START, "load_context")
builder.add_edge("load_context", "route_intent")
builder.add_conditional_edges(
    "route_intent",
    _selected_tool,
    {
        "profile": "profile_tool",
        "matches": "matches_tool",
        "conversation": "conversation_tool",
        "safety": "safety_tool",
        "general": "general_tool",
    },
)
for tool_node in ("profile_tool", "matches_tool", "conversation_tool", "safety_tool", "general_tool"):
    builder.add_edge(tool_node, "generate_response")
builder.add_edge("generate_response", "save_memory")
builder.add_edge("save_memory", END)

agent_graph = builder.compile()


async def run_agent(user_id: int, session_id: str, message: str) -> dict:
    result = await agent_graph.ainvoke({"user_id": user_id, "session_id": session_id, "message": message})
    return {
        "response": result["response"],
        "intent": result["intent"],
        "provider": result["provider"],
        "session_id": result["session_id"],
        "tool_result": result["tool_result"],
    }

