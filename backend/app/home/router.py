"""API trang Tổng quan và thông báo (prefix /api/v1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..security import current_user
from . import notifications, overview

router = APIRouter(tags=["home"])


@router.get("/home")
def home(user: dict = Depends(current_user)) -> dict:
    return overview.build(user["id"])


@router.get("/notifications")
def list_notifications(limit: int = 20, user: dict = Depends(current_user)) -> dict:
    return {"items": notifications.recent(user["id"], limit), "unread": notifications.unread_count(user["id"])}


class ReadIn(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=100)  # bỏ trống = đánh dấu tất cả đã đọc


@router.post("/notifications/read")
def read_notifications(body: ReadIn, user: dict = Depends(current_user)) -> dict:
    notifications.mark_read(user["id"], body.ids)
    return {"unread": notifications.unread_count(user["id"])}
