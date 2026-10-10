import io

import pytest
from app.checkin.imaging import ImageError, process_image
from checkin_helpers import png, vision_env
from PIL import Image


def test_resizes_and_outputs_jpeg(vision_env):
    out = process_image(png(4000, 3000))
    img = Image.open(io.BytesIO(out.data))
    assert img.format == "JPEG" and max(img.size) == 1568


def test_exif_rotation_applied_and_metadata_stripped(vision_env):
    im = Image.new("RGB", (400, 200), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # xoay 90 độ
    exif[0x010F] = "SecretPhone"
    b = io.BytesIO()
    im.save(b, "JPEG", exif=exif)
    out = process_image(b.getvalue())
    img = Image.open(io.BytesIO(out.data))
    assert img.size == (200, 400)
    assert not img.getexif()


def test_rejects_non_image(vision_env):
    with pytest.raises(ImageError):
        process_image(b"not an image at all")


def test_rejects_empty(vision_env):
    with pytest.raises(ImageError):
        process_image(b"")


def test_rejects_too_large(vision_env, monkeypatch):
    monkeypatch.setenv("VISION_MAX_UPLOAD_MB", "0.001")
    from app.checkin import config

    config.get_settings.cache_clear()
    with pytest.raises(ImageError):
        process_image(png(800, 600))


def test_transparent_png_flattened(vision_env):
    im = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    b = io.BytesIO()
    im.save(b, "PNG")
    out = process_image(b.getvalue())
    assert Image.open(io.BytesIO(out.data)).getpixel((5, 5)) == (255, 255, 255)

__all__ = ["vision_env"]  # fixture dùng chung
