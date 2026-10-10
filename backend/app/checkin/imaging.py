"""Chuẩn hóa ảnh check-in trên server.

Trình duyệt đã nén sẵn (~1280px JPEG), nhưng server vẫn kiểm tra lại vì không tin client:
- chỉ nhận JPEG / PNG / WEBP (HEIC nếu có cài pillow-heif),
- xoay đúng chiều theo EXIF rồi XÓA toàn bộ metadata (vị trí GPS, thiết bị…),
- thu cạnh dài về tối đa `image_max_edge`, xuất JPEG.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import get_settings

try:  # HEIC từ iPhone (tùy chọn)
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    _HEIC = True
except Exception:  # pragma: no cover
    _HEIC = False

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"} | ({"HEIF"} if _HEIC else set())


class ImageError(ValueError):
    """Lỗi ảnh, thông điệp hiển thị được cho người dùng."""


@dataclass
class ProcessedImage:
    data: bytes
    width: int
    height: int
    media_type: str = "image/jpeg"


def process_image(raw: bytes) -> ProcessedImage:
    s = get_settings()
    if not raw:
        raise ImageError("Không nhận được ảnh. Hãy chụp hoặc chọn lại ảnh.")
    if len(raw) > s.max_upload_mb * 1024 * 1024:
        raise ImageError(f"Ảnh lớn hơn {s.max_upload_mb:g} MB. Hãy chụp lại hoặc chọn ảnh nhỏ hơn.")
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = (img.format or "").upper()
        img.load()
    except Image.DecompressionBombError as e:
        raise ImageError("Ảnh có độ phân giải quá lớn. Hãy chọn ảnh khác.") from e
    except (UnidentifiedImageError, OSError) as e:
        raise ImageError("File này không phải ảnh hợp lệ. Hãy gửi ảnh JPG hoặc PNG.") from e
    if fmt not in ALLOWED_FORMATS:
        raise ImageError("Định dạng ảnh chưa hỗ trợ. Hãy gửi ảnh JPG, PNG hoặc WEBP.")

    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    elif img.mode == "L":
        img = img.convert("RGB")

    img.thumbnail((s.image_max_edge, s.image_max_edge), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    # Không truyền exif => metadata bị loại bỏ.
    img.save(out, format="JPEG", quality=s.image_jpeg_quality, optimize=True, progressive=True)
    return ProcessedImage(data=out.getvalue(), width=img.width, height=img.height)
