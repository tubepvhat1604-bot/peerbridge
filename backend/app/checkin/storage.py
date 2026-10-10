"""Lưu ảnh check-in.

- DbStorage (mặc định): ảnh nằm trong bảng `vi_images` của chính database. Database được sao lưu liên tục
  (Litestream, xem backend/start.sh) nên ảnh không mất khi server miễn phí ngủ hay deploy lại.
- DiskStorage: lưu file trên đĩa (VISION_STORAGE_BACKEND=disk), dùng khi có ổ đĩa bền.

Ảnh nằm ngoài thư mục /uploads công khai và chỉ được trả qua `/api/v1/checkins/media/...`:
- link ký có hạn (`?exp=&sig=`) do API tạo cho người được xem, dùng thẳng trong thẻ <img>;
- hoặc gửi kèm Bearer token: chủ ảnh luôn xem được, bạn cặp chỉ xem khi check-in đã `done`.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from .config import get_settings
from .db import session_factory

MEDIA_PREFIX = "/api/v1/checkins/media/"
URL_TTL_SECONDS = 3600


class DiskStorage:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _full(self, path: str) -> Path:
        full = (self.root / path).resolve()
        if self.root not in full.parents:
            raise ValueError("Đường dẫn ảnh không hợp lệ")
        return full

    def save(self, path: str, data: bytes, content_type: str = "image/jpeg") -> None:
        full = self._full(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        tmp = full.with_suffix(full.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, full)

    def read(self, path: str) -> bytes:
        return self._full(path).read_bytes()

    def url(self, path: str) -> str:
        return signed_url(path)


class DbStorage:
    def save(self, path: str, data: bytes, content_type: str = "image/jpeg") -> None:
        from .models import VisionImage

        with session_factory()() as db:
            db.merge(VisionImage(path=path, data=data, content_type=content_type))
            db.commit()

    def read(self, path: str) -> bytes:
        from .models import VisionImage

        with session_factory()() as db:
            row = db.get(VisionImage, path)
        if row is None:
            raise FileNotFoundError(path)
        return row.data

    def url(self, path: str) -> str:
        return signed_url(path)


def signed_url(path: str) -> str:
    # Hạn làm tròn theo giờ để trình duyệt cache được ảnh (cùng link trong cùng một giờ).
    exp = (int(time.time()) // URL_TTL_SECONDS + 2) * URL_TTL_SECONDS
    return f"{MEDIA_PREFIX}{quote(path)}?exp={exp}&sig={sign(path, exp)}"


def sign(path: str, exp: int) -> str:
    from ..security import _jwt_secret_bytes

    return hmac.new(_jwt_secret_bytes(), f"checkin-media|{path}|{exp}".encode(), hashlib.sha256).hexdigest()


def verify(path: str, exp: int, sig: str) -> bool:
    return exp >= time.time() and hmac.compare_digest(sign(path, exp), sig)


@lru_cache
def get_storage() -> DbStorage | DiskStorage:
    s = get_settings()
    return DiskStorage(s.image_dir) if s.storage_backend == "disk" else DbStorage()
