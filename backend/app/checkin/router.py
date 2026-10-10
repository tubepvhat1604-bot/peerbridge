"""API check-in của AI Vision. Gắn vào app với prefix /api/v1 (xem app/main.py)."""
from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    UploadFile,
    status,
)
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..security import bearer, current_user, decode_token
from . import service
from .config import get_settings
from .db import get_db
from .imaging import ImageError
from .pipeline import run_pipeline
from .schemas import CheckinOut, ConfirmIn, FeedOut, ReactionIn, TextCheckinIn
from .storage import get_storage, verify

router = APIRouter(tags=["checkin"])


def get_current_user_id(user: dict = Depends(current_user)) -> int:
    return user["id"]


def _err(e: service.ServiceError) -> HTTPException:
    return HTTPException(e.status_code, e.message)


def _valid_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "Mã check-in không hợp lệ.") from e


async def _read_limited(file: UploadFile) -> bytes:
    limit = int(get_settings().max_upload_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Ảnh lớn hơn {get_settings().max_upload_mb:g} MB. Hãy chọn ảnh nhỏ hơn.")
    return data


# ------------------------------------------------------------------ ảnh (có kiểm tra quyền)
@router.get("/checkins/media/{path:path}", include_in_schema=False)
def media(
    path: str,
    exp: int | None = None,
    sig: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
):
    storage = get_storage()
    if exp is not None and sig:
        allowed = verify(path, exp, sig)
    elif credentials:
        allowed = service.media_allowed(db, decode_token(credentials.credentials), path)
    else:
        raise HTTPException(401, "Thiếu Bearer token")
    if not allowed:
        raise HTTPException(404, "Không tìm thấy ảnh.")
    try:
        data = storage.read(path)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, "Không tìm thấy ảnh.") from e
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ số liệu AI
@router.get("/checkins/stats")
def checkin_stats(days: int = 7, _user: int = Depends(get_current_user_id)) -> dict:
    """Tổng hợp chất lượng, độ trễ, chi phí AI Vision trong `days` ngày gần nhất (không có dữ liệu cá nhân)."""
    from .stats import summary

    return summary(max(1, min(days, 90)))


# ------------------------------------------------------------------ check-in
@router.post("/checkins", response_model=CheckinOut, status_code=status.HTTP_202_ACCEPTED)
async def create_checkin(
    background: BackgroundTasks,
    id: str = Form(..., description="UUID do client tạo, chống gửi trùng"),
    image: UploadFile = File(...),
    note: str | None = Form(default=None),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    checkin_id = _valid_id(id)
    raw = await _read_limited(image)
    try:
        checkin, is_new = service.create_photo_checkin(db, user_id, checkin_id, raw, note)
    except ImageError as e:
        raise HTTPException(400, str(e)) from e
    except service.ServiceError as e:
        raise _err(e) from e
    if is_new:
        background.add_task(run_pipeline, checkin.id)
    return service.present(db, checkin, user_id)


@router.post("/checkins/text", response_model=CheckinOut, status_code=status.HTTP_202_ACCEPTED)
def create_text_checkin(
    body: TextCheckinIn,
    background: BackgroundTasks,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        checkin, is_new = service.create_text_checkin(db, user_id, _valid_id(body.id), body.note, body.plan_item_id)
    except service.ServiceError as e:
        raise _err(e) from e
    if is_new and checkin.status == "processing":
        background.add_task(run_pipeline, checkin.id)
    return service.present(db, checkin, user_id)


@router.get("/checkins/{checkin_id}", response_model=CheckinOut)
def get_checkin(checkin_id: str, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        checkin = service.get_visible(db, user_id, _valid_id(checkin_id))
    except service.ServiceError as e:
        raise _err(e) from e
    return service.present(db, checkin, user_id)


@router.post("/checkins/{checkin_id}/confirm", response_model=CheckinOut)
def confirm_checkin(
    checkin_id: str, body: ConfirmIn, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)
):
    try:
        checkin = service.confirm(db, user_id, _valid_id(checkin_id), body.plan_item_id)
    except service.ServiceError as e:
        raise _err(e) from e
    return service.present(db, checkin, user_id)


@router.post("/checkins/{checkin_id}/reactions", response_model=CheckinOut)
def react(checkin_id: str, body: ReactionIn, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        checkin = service.react(db, user_id, _valid_id(checkin_id), body.emoji, body.comment)
    except service.ServiceError as e:
        raise _err(e) from e
    return service.present(db, checkin, user_id)


# ------------------------------------------------------------------ trang chủ cặp
@router.get("/pairs/me/feed", response_model=FeedOut)
def get_feed(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        return service.feed(db, user_id)
    except service.ServiceError as e:
        raise _err(e) from e


@router.post("/pairs/{pair_id}/nudge")
def nudge(pair_id: int = Path(gt=0), user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        return {"message": service.nudge(db, user_id, pair_id)}
    except service.ServiceError as e:
        raise _err(e) from e
