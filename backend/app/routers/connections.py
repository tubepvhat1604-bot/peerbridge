from fastapi import APIRouter, Depends, HTTPException, Path

from ..schemas import ConnectionCreateRequest, ConnectionResponse, ConnectionsResponse
from ..security import current_user
from ..services.connections import (
    ConnectionForbiddenError,
    ConnectionInvalidStateError,
    ConnectionNotFoundError,
    ConnectionSelfRequestError,
    ConnectionService,
    ConnectionTargetNotFoundError,
    get_connection_service,
)

router = APIRouter(prefix="/connections", tags=["connections"])


def _connection_http_error(error: Exception) -> HTTPException:
    if isinstance(error, ConnectionSelfRequestError):
        return HTTPException(status_code=400, detail="Cannot request a connection with yourself")
    if isinstance(error, ConnectionForbiddenError):
        return HTTPException(status_code=403, detail="Only the recipient can respond to this connection request")
    if isinstance(error, (ConnectionNotFoundError, ConnectionTargetNotFoundError)):
        return HTTPException(status_code=404, detail="Connection request not found")
    if isinstance(error, ConnectionInvalidStateError):
        return HTTPException(status_code=409, detail="Invalid connection request state transition")
    return HTTPException(status_code=500, detail="Could not process connection request")


@router.get("", response_model=ConnectionsResponse)
def list_connections(
    user: dict = Depends(current_user),
    service: ConnectionService = Depends(get_connection_service),
) -> ConnectionsResponse:
    try:
        return service.list_connections(user)
    except ConnectionForbiddenError as error:
        raise _connection_http_error(error) from error


@router.post("", response_model=ConnectionResponse, status_code=201)
def create_connection_request(
    payload: ConnectionCreateRequest,
    user: dict = Depends(current_user),
    service: ConnectionService = Depends(get_connection_service),
) -> ConnectionResponse:
    try:
        return service.create_connection_request(user, payload)
    except (
        ConnectionForbiddenError,
        ConnectionInvalidStateError,
        ConnectionSelfRequestError,
        ConnectionTargetNotFoundError,
    ) as error:
        raise _connection_http_error(error) from error


@router.post("/{connection_request_id}/accept", response_model=ConnectionResponse)
def accept_connection_request(
    connection_request_id: int = Path(gt=0),
    user: dict = Depends(current_user),
    service: ConnectionService = Depends(get_connection_service),
) -> ConnectionResponse:
    try:
        return service.accept_connection_request(user, connection_request_id)
    except (ConnectionForbiddenError, ConnectionInvalidStateError, ConnectionNotFoundError) as error:
        raise _connection_http_error(error) from error


@router.post("/{connection_request_id}/reject", response_model=ConnectionResponse)
def reject_connection_request(
    connection_request_id: int = Path(gt=0),
    user: dict = Depends(current_user),
    service: ConnectionService = Depends(get_connection_service),
) -> ConnectionResponse:
    try:
        return service.reject_connection_request(user, connection_request_id)
    except (ConnectionForbiddenError, ConnectionInvalidStateError, ConnectionNotFoundError) as error:
        raise _connection_http_error(error) from error
