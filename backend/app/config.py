from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_path: str = "./data/dongdieu.db"
    database_url: str | None = None
    upload_directory: str = "./data/uploads"
    max_upload_mb: int = 5
    rate_limit_per_minute: int = 120
    jwt_secret: SecretStr | None = None
    daily_metrics_job_secret: SecretStr | None = None
    access_token_minutes: int = 1440
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:5500,null"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    @property
    def database_file(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path.resolve()

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.database_file.as_posix()}"

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_directory)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path.resolve()

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
