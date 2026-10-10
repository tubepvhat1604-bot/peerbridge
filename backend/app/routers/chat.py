from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from ..agents.graph import run_agent
from ..db import database, utc_now
from ..schemas import AgentChatRequest, MessageRequest
from ..security import current_user, decode_token
from ..services.content_safety import reject_personal_contact
from ..services.realtime import realtime

router = APIRouter(tags=["chat"])


def _require_match(connection, match_id: int, user_id: int):
    match = connection.execute(
        "SELECT * FROM matches WHERE id=? AND (user_a_id=? OR user_b_id=?)",
        (match_id, user_id, user_id),
    ).fetchone()
    if not match:
        raise HTTPException(status_code=404, detail="Không tìm thấy kết nối")
    return match


@router.get("/matches/{match_id}/messages")
def list_messages(
    match_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    user: dict = Depends(current_user),
) -> dict:
    with database() as connection:
        _require_match(connection, match_id, user["id"])
        read_at = utc_now()
        connection.execute(
            "UPDATE messages SET read_at=? WHERE match_id=? AND sender_id!=? AND read_at IS NULL",
            (read_at, match_id, user["id"]),
        )
        rows = connection.execute(
            """SELECT m.id, m.match_id, m.sender_id, p.display_name AS sender_name,
                      m.content, m.read_at, m.created_at
               FROM messages m JOIN profiles p ON p.user_id=m.sender_id
               WHERE m.match_id=? ORDER BY m.id DESC LIMIT ?""",
            (match_id, limit),
        ).fetchall()
    items = [dict(row) for row in reversed(rows)]
    return {"items": items, "count": len(items)}


@router.post("/matches/{match_id}/messages", status_code=201)
async def send_message(match_id: int, payload: MessageRequest, user: dict = Depends(current_user)) -> dict:
    reject_personal_contact(payload.content, "Tin nhắn")
    with database() as connection:
        _require_match(connection, match_id, user["id"])
        cursor = connection.execute(
            "INSERT INTO messages(match_id, sender_id, content, created_at) VALUES (?, ?, ?, ?)",
            (match_id, user["id"], payload.content, utc_now()),
        )
        row = connection.execute(
            "SELECT id, match_id, sender_id, content, read_at, created_at FROM messages WHERE id=?",
            (cursor.lastrowid,),
        ).fetchone()
    message = dict(row)
    await realtime.broadcast_match(match_id, {"type": "message", "match_id": match_id, "message": message})
    return message


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")) -> None:
    try:
        user_id = decode_token(token)
        with database() as connection:
            user = connection.execute(
                "SELECT id FROM users WHERE id=? AND is_seed=0", (user_id,)
            ).fetchone()
        if not user:
            raise ValueError("user not found")
    except (HTTPException, ValueError):
        await websocket.close(code=4401, reason="Token không hợp lệ")
        return
    await realtime.connect(user_id, websocket)
    await realtime.broadcast_presence(user_id, True)
    await websocket.send_json({"type": "ready", "user_id": user_id})
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        realtime.disconnect(user_id, websocket)
        if not realtime.is_online(user_id):
            await realtime.broadcast_presence(user_id, False)


@router.post("/agent/chat")
async def agent_chat(payload: AgentChatRequest, user: dict = Depends(current_user)) -> dict:
    return await run_agent(user["id"], payload.session_id, payload.message.strip())


@router.get("/agent/status")
def agent_status() -> dict:
    return {
        "status": "ready",
        "engine": "LangGraph",
        "nodes": ["load_context", "route_intent", "tools", "generate_response", "save_memory"],
        "intents": ["profile", "matches", "conversation", "safety", "general"],
    }


@router.get("/agent/history")
def agent_history(
    session_id: str = Query(default="default", min_length=1, max_length=80),
    user: dict = Depends(current_user),
) -> dict:
    with database() as connection:
        rows = connection.execute(
            """SELECT role, content, created_at FROM agent_messages
               WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT 20""",
            (user["id"], session_id),
        ).fetchall()
    return {"items": [dict(row) for row in reversed(rows)]}
