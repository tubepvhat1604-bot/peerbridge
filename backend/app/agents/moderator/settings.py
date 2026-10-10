"""Cấu hình riêng của moderator, tách khỏi app/config.py dùng chung."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModeratorSettings(BaseSettings):
    """Đọc từ .env; biến không liên quan bị bỏ qua."""

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    qdrant_url: str = "http://localhost:6333"
    embedding_model: str = "intfloat/multilingual-e5-large"
    qdrant_collection: str = "course_materials"
    rag_top_k: int = Field(default=4, ge=1)
    rag_min_score: float = Field(default=0.78, ge=0, le=1)
    retriever_provider: Literal["fake", "qdrant", "local"] = "fake"
    # provider "local": BM25 trên file data/courses/<course_id>/, không cần Qdrant.
    rag_corpus_dir: str = str(Path(__file__).resolve().parents[3] / "data" / "courses")
    rag_local_min_score: float = Field(default=0.35, ge=0, le=1)
    # Khoá dùng cho phòng học chưa được gán khoá nào (bảng session_courses); để trống = không tra tài liệu.
    rag_default_course_id: str = ""
    risk_escalate_threshold: float = Field(default=0.8, ge=0, le=1)
    llm_provider: Literal["fake", "openai"] = "fake"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4.1-mini"
    llm_timeout_seconds: float = Field(default=20.0, gt=0)
    llm_json_mode: bool = True
    output_guard_llm_judge: bool = False
    # Tin chat thường (chào, ok, hẹn giờ) chỉ dùng luật, không gọi LLM; xem prefilter.py.
    moderation_prefilter_enabled: bool = True
    max_llm_calls: int = Field(default=3, ge=1, le=3)
    moderation_timeout_seconds: float = Field(default=30, gt=0)
    moderation_messages_per_minute: int = Field(default=30, ge=1)
    max_socratic_turns: int = Field(default=6, ge=1, le=20)

    @property
    def effective_llm_api_key(self) -> str:
        """Key dùng thực tế: LLM_API_KEY, nếu trống thì OPENAI_API_KEY."""
        return (self.llm_api_key.get_secret_value() or self.openai_api_key.get_secret_value()).strip()


@lru_cache
def get_moderator_settings() -> ModeratorSettings:
    """Trả settings đã cache."""
    return ModeratorSettings()
