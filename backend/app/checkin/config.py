"""Cấu hình cho module check-in (AI Vision).

Biến môi trường riêng của module có tiền tố VISION_ (ví dụ VISION_LLM_PROVIDER=openai).
Key OpenAI và nơi lưu file dùng chung với app (OPENAI_API_KEY, UPLOAD_DIRECTORY).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..config import get_settings as get_app_settings


class CheckinSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VISION_", env_file=(".env", "backend/.env"), env_file_encoding="utf-8", extra="ignore"
    )

    timezone: str = "Asia/Ho_Chi_Minh"
    # Check-in trước giờ này được tính cho ngày hôm trước (học khuya).
    day_cutoff_hour: int = 3

    # --- LLM ---
    # fake: không gọi API, trả kết quả giả định sẵn (dev, test, demo không mạng).
    llm_provider: Literal["openai", "fake"] = "fake"
    # Để trống thì dùng OPENAI_API_KEY chung của app.
    openai_api_key: str = ""
    vision_model: str = "gpt-4.1-mini"
    text_model: str = "gpt-4.1-mini"
    # Độ chi tiết ảnh gửi OpenAI: high (đọc chữ nhỏ trên màn hình tốt hơn) | low (rẻ hơn) | auto
    image_detail: Literal["high", "low", "auto"] = "high"
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 1
    # Giá USD cho mỗi triệu token "vào/ra", để ước tính chi phí. Kiểm tra lại trang giá chính thức.
    price_table: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "gpt-4.1-mini": (0.40, 1.60),
            "gpt-4.1": (2.00, 8.00),
            "gpt-5-mini": (0.25, 2.00),
            "gpt-5": (1.25, 10.00),
        }
    )

    # --- Ngưỡng quyết định (mục 8.5 CONTEXT.md) ---
    confidence_high: float = 0.75
    confidence_low: float = 0.40
    partner_strength_theta: float = 0.5
    max_confirm_options: int = 3
    max_week_options: int = 6

    # --- Ảnh ---
    max_upload_mb: float = 10.0
    image_max_edge: int = 1568
    image_jpeg_quality: int = 82
    # db: ảnh lưu trong database (được sao lưu cùng dữ liệu). disk: lưu file ở storage_dir.
    storage_backend: Literal["db", "disk"] = "db"
    # Để trống thì lưu ở <UPLOAD_DIRECTORY>/checkins (KHÔNG nằm dưới /uploads công khai).
    storage_dir: str = ""

    # --- Giới hạn chống lạm dụng / chi phí ---
    max_checkins_per_day: int = 10
    # Trần chi phí AI mỗi ngày (USD, mọi người dùng cộng lại). Vượt trần: không gọi AI, người dùng tự chọn mục.
    daily_budget_usd: float = 2.0
    nudge_cooldown_hours: int = 6
    quiet_hours: tuple[int, int] = (22, 7)
    comment_max_chars: int = 200
    note_max_chars: int = 300

    # --- Tracing (tùy chọn) ---
    langsmith_tracing: bool = False

    @property
    def api_key(self) -> str:
        return self.openai_api_key or get_app_settings().openai_api_key

    @property
    def image_dir(self) -> Path:
        if self.storage_dir:
            return Path(self.storage_dir).resolve()
        # Thư mục riêng cạnh uploads: ảnh check-in chỉ trả qua route có kiểm tra quyền.
        return get_app_settings().upload_path.parent / "checkin_images"


@lru_cache
def get_settings() -> CheckinSettings:
    return CheckinSettings()
