from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM API keys (no prefix, match .env.example)
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Sebastian core
    sebastian_owner_name: str = "Owner"
    sebastian_data_dir: str = "./data"
    sebastian_sandbox_enabled: bool = False

    # Gateway
    sebastian_gateway_host: str = "0.0.0.0"
    sebastian_gateway_port: int = 8000

    # JWT
    sebastian_jwt_secret: str = "change-me-in-production"
    sebastian_jwt_algorithm: str = "HS256"
    sebastian_jwt_expire_minutes: int = 43200  # 30 days

    # Owner password (bcrypt hash, set via `sebastian init` CLI)
    sebastian_owner_password_hash: str = ""

    # DB override (empty = auto-derive from data_dir)
    sebastian_db_url: str = ""

    # LLM model selection
    sebastian_model: str = "claude-opus-4-6"

    # LLM max tokens per request (spec: 16000)
    llm_max_tokens: int = 16000

    @property
    def database_url(self) -> str:
        if self.sebastian_db_url:
            return self.sebastian_db_url
        data_path = Path(self.sebastian_data_dir)
        return f"sqlite+aiosqlite:///{data_path}/sebastian.db"

    @property
    def sessions_dir(self) -> Path:
        return Path(self.sebastian_data_dir) / "sessions"


settings = Settings()


def ensure_data_dir() -> None:
    """Create the data directory and sessions subdirectories."""
    data = Path(settings.sebastian_data_dir)
    data.mkdir(parents=True, exist_ok=True)
    (data / "sessions").mkdir(exist_ok=True)
    (data / "sessions" / "sebastian").mkdir(exist_ok=True)
    (data / "sessions" / "subagents").mkdir(exist_ok=True)


__all__ = ["Settings", "settings", "ensure_data_dir"]
