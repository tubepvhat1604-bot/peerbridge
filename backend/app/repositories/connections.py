import sqlite3
from typing import Any

from ..enums import ConnectionStatus

ConnectionRecord = dict[str, Any]
ConnectionsRecord = dict[str, list[dict[str, Any]]]


class ConnectionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def student_exists(self, user_id: int) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM users WHERE id = ? AND role = 'STUDENT' AND is_seed = 0",
            (user_id,),
        ).fetchone()
        return row is not None

    def has_pending_request_between(self, left_user_id: int, right_user_id: int) -> bool:
        row = self.connection.execute(
            """SELECT 1 FROM connection_requests
               WHERE status = ?
                 AND ((requester_id = ? AND recipient_id = ?) OR (requester_id = ? AND recipient_id = ?))""",
            (
                ConnectionStatus.PENDING.value,
                left_user_id,
                right_user_id,
                right_user_id,
                left_user_id,
            ),
        ).fetchone()
        return row is not None

    def peer_match_exists_between(self, left_user_id: int, right_user_id: int) -> bool:
        user_a_id, user_b_id = sorted((left_user_id, right_user_id))
        row = self.connection.execute(
            "SELECT 1 FROM peer_matches WHERE user_a_id = ? AND user_b_id = ?",
            (user_a_id, user_b_id),
        ).fetchone()
        return row is not None

    def create_connection_request(self, requester_id: int, recipient_id: int, created_at: str) -> ConnectionRecord:
        cursor = self.connection.execute(
            """INSERT INTO connection_requests(requester_id, recipient_id, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (requester_id, recipient_id, ConnectionStatus.PENDING.value, created_at),
        )
        record = self.get_connection_request(int(cursor.lastrowid))
        if record is None:
            raise RuntimeError("Created connection request could not be loaded")
        return record

    def get_connection_request(self, connection_request_id: int) -> ConnectionRecord | None:
        row = self.connection.execute(
            """SELECT cr.id, cr.requester_id, cr.recipient_id, cr.status, cr.created_at, cr.responded_at,
                      pm.id AS peer_match_id
               FROM connection_requests cr
               LEFT JOIN peer_matches pm ON pm.connection_request_id = cr.id
               WHERE cr.id = ?""",
            (connection_request_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_connections(self, user_id: int) -> ConnectionsRecord:
        incoming = self.connection.execute(
            """SELECT cr.id, cr.requester_id, cr.recipient_id, cr.status, cr.created_at, cr.responded_at,
                      p.user_id AS peer_user_id, p.display_name AS peer_display_name,
                      p.school AS peer_school, p.major AS peer_major
               FROM connection_requests cr
               JOIN profiles p ON p.user_id = cr.requester_id
               WHERE cr.recipient_id = ? AND cr.status = ?
               ORDER BY cr.id DESC""",
            (user_id, ConnectionStatus.PENDING.value),
        ).fetchall()
        sent = self.connection.execute(
            """SELECT cr.id, cr.requester_id, cr.recipient_id, cr.status, cr.created_at, cr.responded_at,
                      p.user_id AS peer_user_id, p.display_name AS peer_display_name,
                      p.school AS peer_school, p.major AS peer_major
               FROM connection_requests cr
               JOIN profiles p ON p.user_id = cr.recipient_id
               WHERE cr.requester_id = ? AND cr.status = ?
               ORDER BY cr.id DESC""",
            (user_id, ConnectionStatus.PENDING.value),
        ).fetchall()
        connected = self.connection.execute(
            """SELECT pm.id AS peer_match_id, pm.connection_request_id,
                      cr.requester_id, cr.recipient_id, pm.created_at AS connected_at,
                      p.user_id AS peer_user_id, p.display_name AS peer_display_name,
                      p.school AS peer_school, p.major AS peer_major
               FROM peer_matches pm
               JOIN connection_requests cr ON cr.id = pm.connection_request_id
               JOIN profiles p ON p.user_id = CASE WHEN pm.user_a_id = ? THEN pm.user_b_id ELSE pm.user_a_id END
               WHERE pm.user_a_id = ? OR pm.user_b_id = ?
               ORDER BY pm.id DESC""",
            (user_id, user_id, user_id),
        ).fetchall()

        return {
            "incoming": [self._connection_summary(row) for row in incoming],
            "sent": [self._connection_summary(row) for row in sent],
            "connected": [self._connected_summary(row) for row in connected],
        }

    def mark_connection_request(
        self,
        connection_request_id: int,
        status: ConnectionStatus,
        responded_at: str,
    ) -> ConnectionRecord:
        self.connection.execute(
            "UPDATE connection_requests SET status = ?, responded_at = ? WHERE id = ?",
            (status.value, responded_at, connection_request_id),
        )
        record = self.get_connection_request(connection_request_id)
        if record is None:
            raise RuntimeError("Updated connection request could not be loaded")
        return record

    def create_peer_match(self, connection_request_id: int, requester_id: int, recipient_id: int, created_at: str) -> int:
        user_a_id, user_b_id = sorted((requester_id, recipient_id))
        cursor = self.connection.execute(
            """INSERT INTO peer_matches(connection_request_id, user_a_id, user_b_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (connection_request_id, user_a_id, user_b_id, created_at),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _peer_profile(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "user_id": int(row["peer_user_id"]),
            "display_name": row["peer_display_name"],
            "school": row["peer_school"],
            "major": row["peer_major"],
        }

    @classmethod
    def _connection_summary(cls, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "requester_id": int(row["requester_id"]),
            "recipient_id": int(row["recipient_id"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "responded_at": row["responded_at"],
            "peer": cls._peer_profile(row),
        }

    @classmethod
    def _connected_summary(cls, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "peer_match_id": int(row["peer_match_id"]),
            "connection_request_id": int(row["connection_request_id"]),
            "requester_id": int(row["requester_id"]),
            "recipient_id": int(row["recipient_id"]),
            "connected_at": row["connected_at"],
            "peer": cls._peer_profile(row),
        }
