from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM API keys are managed via the Settings page (stored in DB, encrypted)
    openai_api_key: str = ""  # reserved, not currently used

    # Sebastian core
    sebastian_owner_name: str = "Owner"
    sebastian_data_dir: str = str(Path.home() / ".sebastian")
    sebastian_sandbox_enabled: bool = False

    # Gateway
    sebastian_gateway_host: str = "0.0.0.0"
    sebastian_gateway_port: int = 8823

    # JWT
    sebastian_jwt_secret: str = "change-me-in-production"
    sebastian_jwt_algorithm: str = "HS256"
    sebastian_jwt_expire_minutes: int = 43200  # 30 days

    # JWT secret key file path (empty = data_dir/secret.key)
    sebastian_secret_key_path: str = ""

    # Owner password (bcrypt hash, set via `sebastian init` CLI)
    sebastian_owner_password_hash: str = ""

    # DB override (empty = auto-derive from data_dir)
    sebastian_db_url: str = ""

    # LLM model selection
    sebastian_model: str = "claude-opus-4-6"

    # LLM max tokens per request
    # 32000 覆盖 Anthropic effort capability 下 high 档位 budget=24576 + 足够正文空间
    llm_max_tokens: int = 32000

    # Logging toggles (initial state; can be changed at runtime via API)
    sebastian_log_llm_stream: bool = False
    sebastian_log_sse: bool = False

    @property
    def data_dir(self) -> Path:
        return Path(self.sebastian_data_dir).expanduser().resolve()

    @property
    def database_url(self) -> str:
        if self.sebastian_db_url:
            return self.sebastian_db_url
        return f"sqlite+aiosqlite:///{self.data_dir}/sebastian.db"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def extensions_dir(self) -> Path:
        return self.data_dir / "extensions"

    @property
    def skills_extensions_dir(self) -> Path:
        return self.extensions_dir / "skills"

    @property
    def agents_extensions_dir(self) -> Path:
        return self.extensions_dir / "agents"

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "workspace"

    def resolved_secret_key_path(self) -> Path:
        if self.sebastian_secret_key_path:
            return Path(self.sebastian_secret_key_path).expanduser()
        return Path(self.sebastian_data_dir).expanduser() / "secret.key"


settings = Settings()


def ensure_data_dir() -> None:
    """Create required data directory structure."""
    for sub in (
        "sessions/sebastian",
        "extensions/skills",
        "extensions/agents",
        "workspace",
    ):
        (settings.data_dir / sub).mkdir(parents=True, exist_ok=True)


__all__ = ["Settings", "settings", "ensure_data_dir"]
