"""API tóm tắt phiên (sinh viên) và giám sát phiên học (Admin). Đặt dưới /api/v1."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ..admin_roles import is_admin, public_role
from ..db import database
from ..security import current_user
from . import service
from .transcript import load_session

router = APIRouter(tags=["session-review"])


def _require_admin(user: dict) -> None:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Chỉ Admin mới xem được trang này")


def _require_access(user: dict, session_id: int) -> dict[str, Any]:
    with database() as connection:
        session = load_session(connection, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên học")
    if not is_admin(user) and int(user["id"]) not in {int(session["learner_id"]), int(session["helper_id"])}:
        raise HTTPException(status_code=403, detail="Bạn không thuộc phiên học này")
    return session


@router.get("/admin/me")
def whoami(user: dict = Depends(current_user)) -> dict[str, Any]:
    return {"user_id": int(user["id"]), "role": public_role(str(user["role"])), "is_admin": is_admin(user)}


@router.get("/sessions/{session_id}/review")
def get_session_review(session_id: int = Path(gt=0), user: dict = Depends(current_user)) -> dict[str, Any]:
    _require_access(user, session_id)
    with database() as connection:
        review = service.get_review(connection, session_id)
    return {"review": review if is_admin(user) else service.student_view(review)}


@router.post("/sessions/{session_id}/review")
async def create_session_review(session_id: int = Path(gt=0), user: dict = Depends(current_user)) -> dict[str, Any]:
    """Kết thúc phiên: tóm tắt nội dung đã trao đổi (một lần gọi AI; không có tin mới thì trả bản cũ)."""
    _require_access(user, session_id)
    review = await service.review_session(session_id, int(user["id"]))
    return {"review": review if is_admin(user) else service.student_view(review)}


@router.get("/admin/overview")
def admin_overview(user: dict = Depends(current_user)) -> dict[str, Any]:
    _require_admin(user)
    with database() as connection:
        return service.overview(connection)


@router.get("/admin/sessions")
def admin_sessions(limit: int = Query(default=100, ge=1, le=500), user: dict = Depends(current_user)) -> dict[str, Any]:
    _require_admin(user)
    with database() as connection:
        items = service.session_rows(connection, limit)
    return {"items": items, "count": len(items)}


@router.get("/admin/sessions/{session_id}")
def admin_session_detail(session_id: int = Path(gt=0), user: dict = Depends(current_user)) -> dict[str, Any]:
    _require_admin(user)
    session = _require_access(user, session_id)
    with database() as connection:
        review = service.get_review(connection, session_id)
        verdict = service.session_verdict(connection, session)
    return {"session": session, "review": review, "verdict": verdict}


@router.post("/admin/sessions/{session_id}/review")
async def admin_review_session(session_id: int = Path(gt=0), user: dict = Depends(current_user)) -> dict[str, Any]:
    """Admin bấm "Chấm phiên": chấm lại bằng AI (LLM-as-Judge) nếu còn trần chi phí, không thì bằng luật."""
    _require_admin(user)
    _require_access(user, session_id)
    return {"review": await service.review_session(session_id, int(user["id"]), force=True)}
