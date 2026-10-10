from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from ..enums import ModerationAction
from ..services.moderation_agent import ModerationAgentProtocol, get_moderation_agent
from ..services.study_room import (
    StudyRoomAuthError,
    StudyRoomForbiddenError,
    StudyRoomRateLimitError,
    StudyRoomService,
    StudyRoomValidationError,
    study_room_connections,
)

router = APIRouter(tags=["study-room"])


@router.websocket("/ws/sessions/{session_id}")
async def study_room_websocket(
    websocket: WebSocket,
    session_id: int,
    token: str = Query(default=""),
    moderation_agent: ModerationAgentProtocol = Depends(get_moderation_agent),
) -> None:
    service = StudyRoomService(moderation_agent)
    try:
        user = service.identify_user(token)
        session = service.require_session_member(session_id, user.id)
    except StudyRoomAuthError:
        await websocket.close(code=4401, reason="Unauthorized")
        return
    except StudyRoomForbiddenError:
        await websocket.close(code=4403, reason="Study session access denied")
        return

    await study_room_connections.connect(session.id, websocket)
    await study_room_connections.broadcast(
        session.id,
        service.session_status_event(session.id, user.id, "JOINED", service.tutor_status(session.id, user.id)),
    )
    try:
        while True:
            payload = await websocket.receive_json()
            try:
                events = await service.handle_client_event(session, user, payload)
            except StudyRoomRateLimitError:
                await websocket.send_json(service.error_event("RATE_LIMITED", "Bạn gửi quá nhanh; vui lòng thử lại sau."))
                continue
            except StudyRoomValidationError:
                await websocket.send_json(
                    service.error_event(
                        code="INVALID_PAYLOAD",
                        message="Study room messages must be CHAT_MESSAGE events with non-empty content.",
                    )
                )
                continue
            except Exception:
                await websocket.send_json(
                    service.error_event(
                        code="MESSAGE_PROCESSING_FAILED",
                        message="Could not process study room message.",
                    )
                )
                continue
            for event in events:
                result = next((item["result"] for item in events if item["type"] == "MODERATION_RESULT"), {})
                if result.get("action") in {ModerationAction.ALLOW.value, ModerationAction.GUIDE.value}:
                    await study_room_connections.broadcast(session.id, event)
                else:
                    await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        study_room_connections.disconnect(session.id, websocket)
        await study_room_connections.broadcast(
            session.id,
            service.session_status_event(session.id, user.id, "LEFT"),
        )
