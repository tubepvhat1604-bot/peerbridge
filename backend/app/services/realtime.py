from collections import defaultdict

from fastapi import WebSocket

from ..db import database


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[user_id].add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        self.connections[user_id].discard(websocket)
        if not self.connections[user_id]:
            self.connections.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        return bool(self.connections.get(user_id))

    async def send_user(self, user_id: int, payload: dict) -> None:
        stale = []
        for websocket in tuple(self.connections.get(user_id, ())):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(user_id, websocket)

    async def broadcast_match(self, match_id: int, payload: dict) -> None:
        with database() as connection:
            match = connection.execute(
                "SELECT user_a_id, user_b_id FROM matches WHERE id=?", (match_id,)
            ).fetchone()
        if not match:
            return
        await self.send_user(match["user_a_id"], payload)
        await self.send_user(match["user_b_id"], payload)

    async def broadcast_presence(self, user_id: int, online: bool) -> None:
        with database() as connection:
            rows = connection.execute(
                """SELECT CASE WHEN user_a_id=? THEN user_b_id ELSE user_a_id END AS other_id
                   FROM matches WHERE user_a_id=? OR user_b_id=?""",
                (user_id, user_id, user_id),
            ).fetchall()
        payload = {"type": "presence", "user_id": user_id, "online": online}
        for row in rows:
            await self.send_user(row["other_id"], payload)


realtime = ConnectionManager()
