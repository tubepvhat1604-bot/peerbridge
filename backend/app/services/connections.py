import sqlite3
from collections.abc import Generator

from ..db import database, utc_now
from ..enums import ConnectionStatus, Role
from ..repositories.connections import ConnectionRepository
from ..schemas import ConnectionCreateRequest, ConnectionResponse, ConnectionsResponse


class ConnectionTargetNotFoundError(Exception):
    """Raised when a requested student account does not exist."""


class ConnectionNotFoundError(Exception):
    """Raised when a connection request does not exist."""


class ConnectionForbiddenError(Exception):
    """Raised when a user is not allowed to transition a connection request."""


class ConnectionInvalidStateError(Exception):
    """Raised when a connection request transition is not valid."""


class ConnectionSelfRequestError(Exception):
    """Raised when a student requests a connection with themselves."""


def notify_connection(connection, to_user: int, from_user: int, *, accepted: bool) -> None:
    """Thông báo trong app cho lời mời kết nối / chấp nhận (ghi cùng giao dịch, lỗi thì bỏ qua)."""
    from ..home import notifications

    row = connection.execute("SELECT display_name FROM profiles WHERE user_id=?", (from_user,)).fetchone()
    name = row["display_name"] if row else "Một bạn"
    if accepted:
        notifications.add(to_user, "connection_accepted", f"{name} đã chấp nhận kết nối",
                          "Hai bạn có thể lập kế hoạch và check-in cùng nhau.", "plan", connection=connection)
    else:
        notifications.add(to_user, "connection_request", f"{name} muốn kết nối học cùng bạn",
                          "Xem lời mời trong mục Kết nối.", "connections", connection=connection)


class ConnectionService:
    def __init__(self, repository: ConnectionRepository) -> None:
        self.repository = repository

    def create_connection_request(self, user: dict, payload: ConnectionCreateRequest) -> ConnectionResponse:
        requester_id = self._current_student_id(user)
        recipient_id = payload.recipient_id
        if requester_id == recipient_id:
            raise ConnectionSelfRequestError("Students cannot request themselves")
        if not self.repository.student_exists(recipient_id):
            raise ConnectionTargetNotFoundError("Recipient student not found")
        if self.repository.peer_match_exists_between(requester_id, recipient_id):
            raise ConnectionInvalidStateError("Students are already matched")
        if self.repository.has_pending_request_between(requester_id, recipient_id):
            raise ConnectionInvalidStateError("A pending connection request already exists")

        response = ConnectionResponse(
            **self.repository.create_connection_request(
                requester_id=requester_id,
                recipient_id=recipient_id,
                created_at=utc_now(),
            )
        )
        notify_connection(self.repository.connection, recipient_id, requester_id, accepted=False)
        # A yield dependency may close after HTTP bytes have already been sent.
        # Commit the successful mutation before clients can follow it with accept/read.
        self.repository.connection.commit()
        return response

    def list_connections(self, user: dict) -> ConnectionsResponse:
        user_id = self._current_student_id(user)
        return ConnectionsResponse(**self.repository.list_connections(user_id))

    def accept_connection_request(self, user: dict, connection_request_id: int) -> ConnectionResponse:
        return self._transition_connection_request(
            user=user,
            connection_request_id=connection_request_id,
            status=ConnectionStatus.MATCHED,
            create_peer_match=True,
        )

    def reject_connection_request(self, user: dict, connection_request_id: int) -> ConnectionResponse:
        return self._transition_connection_request(
            user=user,
            connection_request_id=connection_request_id,
            status=ConnectionStatus.REJECTED,
            create_peer_match=False,
        )

    def _transition_connection_request(
        self,
        user: dict,
        connection_request_id: int,
        status: ConnectionStatus,
        *,
        create_peer_match: bool,
    ) -> ConnectionResponse:
        recipient_id = self._current_student_id(user)
        record = self.repository.get_connection_request(connection_request_id)
        if record is None:
            raise ConnectionNotFoundError("Connection request not found")
        if int(record["recipient_id"]) != recipient_id:
            raise ConnectionForbiddenError("Only the recipient can respond to a connection request")
        if record["status"] != ConnectionStatus.PENDING.value:
            raise ConnectionInvalidStateError("Connection request is not pending")

        responded_at = utc_now()
        if create_peer_match:
            try:
                self.repository.create_peer_match(
                    connection_request_id=connection_request_id,
                    requester_id=int(record["requester_id"]),
                    recipient_id=int(record["recipient_id"]),
                    created_at=responded_at,
                )
            except sqlite3.IntegrityError as error:
                raise ConnectionInvalidStateError("Peer match already exists") from error

        updated = self.repository.mark_connection_request(
            connection_request_id=connection_request_id,
            status=status,
            responded_at=responded_at,
        )
        response = ConnectionResponse(**updated)
        if create_peer_match:
            notify_connection(self.repository.connection, int(record["requester_id"]), recipient_id, accepted=True)
        self.repository.connection.commit()
        return response

    @staticmethod
    def _current_student_id(user: dict) -> int:
        if str(user.get("role")) != Role.STUDENT.value:
            raise ConnectionForbiddenError("Only students can use connection requests")
        return int(user["id"])


def get_connection_service() -> Generator[ConnectionService, None, None]:
    with database() as connection:
        yield ConnectionService(ConnectionRepository(connection))
