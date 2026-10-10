"""Compatibility wrapper for callers using the old service location."""

from ..agents.graph import run_agent


async def chat_with_agent(user_id: int, session_id: str, message: str) -> dict:
    return await run_agent(user_id, session_id, message)

