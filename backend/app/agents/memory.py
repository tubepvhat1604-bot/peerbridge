from ..db import database, utc_now


def load_memory(user_id: int, session_id: str, limit: int = 8) -> list[dict[str, str]]:
    with database() as connection:
        rows = connection.execute(
            """SELECT role, content FROM agent_messages
               WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT ?""",
            (user_id, session_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def save_turn(user_id: int, session_id: str, message: str, response: str) -> None:
    timestamp = utc_now()
    with database() as connection:
        connection.executemany(
            "INSERT INTO agent_messages(user_id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            [
                (user_id, session_id, "user", message, timestamp),
                (user_id, session_id, "assistant", response, timestamp),
            ],
        )

