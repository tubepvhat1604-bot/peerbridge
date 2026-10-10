from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile

from ..cache import cache
from ..config import get_settings
from ..db import database, utc_now
from ..schemas import ProfileMeResponse, ProfileMeUpdate, ProfileUpdate
from ..security import current_user
from ..services.profiles import (
    ProfileAccessDeniedError,
    ProfileNotFoundError,
    ProfileService,
    get_profile_service,
)

router = APIRouter(prefix="/profiles", tags=["profiles"])
ProfilePayload = Annotated[ProfileMeUpdate | ProfileUpdate, Body(...)]


def _profile_http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProfileNotFoundError):
        return HTTPException(status_code=404, detail="Chưa có hồ sơ")
    if isinstance(error, ProfileAccessDeniedError):
        return HTTPException(status_code=403, detail="Không thể sửa hồ sơ của người dùng khác")
    return HTTPException(status_code=500, detail="Không thể xử lý hồ sơ")


@router.get("/me", response_model=ProfileMeResponse)
def my_profile(
    user: dict = Depends(current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileMeResponse:
    try:
        return service.get_my_profile(user)
    except (ProfileNotFoundError, ProfileAccessDeniedError) as error:
        raise _profile_http_error(error) from error


@router.put("/me", response_model=ProfileMeResponse)
def update_profile(
    payload: ProfilePayload,
    user: dict = Depends(current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileMeResponse:
    try:
        return service.update_my_profile(user, payload)
    except (ProfileNotFoundError, ProfileAccessDeniedError) as error:
        raise _profile_http_error(error) from error


@router.post("/me/avatar", status_code=201)
async def upload_avatar(file: UploadFile = File(...), user: dict = Depends(current_user)) -> dict:
    settings = get_settings()
    allowed = {
        "image/jpeg": (".jpg", (b"\xff\xd8\xff",)),
        "image/png": (".png", (b"\x89PNG\r\n\x1a\n",)),
        "image/webp": (".webp", (b"RIFF",)),
    }
    if file.content_type not in allowed:
        raise HTTPException(status_code=415, detail="Chỉ hỗ trợ ảnh JPEG, PNG hoặc WebP")
    limit = settings.max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if not content or len(content) > limit:
        raise HTTPException(status_code=413, detail=f"Ảnh phải nhỏ hơn {settings.max_upload_mb} MB")
    extension, signatures = allowed[file.content_type]
    if not any(content.startswith(signature) for signature in signatures):
        raise HTTPException(status_code=415, detail="Nội dung file ảnh không hợp lệ")
    if file.content_type == "image/webp" and content[8:12] != b"WEBP":
        raise HTTPException(status_code=415, detail="Nội dung WebP không hợp lệ")
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    filename = f"avatar-{user['id']}-{uuid4().hex}{extension}"
    destination: Path = settings.upload_path / filename
    destination.write_bytes(content)
    avatar_url = f"/uploads/{filename}"
    with database() as connection:
        connection.execute(
            "UPDATE profiles SET avatar_url=?, updated_at=? WHERE user_id=?",
            (avatar_url, utc_now(), user["id"]),
        )
    cache.delete_prefix("discover:")
    return {"avatar_url": avatar_url}
