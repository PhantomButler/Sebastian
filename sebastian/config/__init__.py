from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""

    sebastian_owner_name: str = "Owner"
    sebastian_data_dir: str = str(Path.home() / ".sebastian")
    sebastian_sandbox_enabled: bool = False
    sebastian_memory_enabled: bool = True

    sebastian_gateway_host: str = "0.0.0.0"
    sebastian_gateway_port: int = 8823

    sebastian_jwt_algorithm: str = "HS256"
    sebastian_jwt_expire_minutes: int = 43200

    sebastian_secret_key_path: str = ""
    sebastian_db_url: str = ""

    sebastian_model: str = "claude-opus-4-6"
    llm_max_tokens: int = 32000

    sebastian_log_llm_stream: bool = False
    sebastian_log_sse: bool = False

    @property
    def data_dir(self) -> Path:
        """Root install / data directory (~/.sebastian by default)."""
        return Path(self.sebastian_data_dir).expanduser().resolve()

    @property
    def user_data_dir(self) -> Path:
        """User data subdir (db, secret.key, workspace, extensions)."""
        return self.data_dir / "data"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def run_dir(self) -> Path:
        return self.data_dir / "run"

    @property
    def database_url(self) -> str:
        if self.sebastian_db_url:
            return self.sebastian_db_url
        return f"sqlite+aiosqlite:///{self.user_data_dir}/sebastian.db"

    @property
    def extensions_dir(self) -> Path:
        return self.user_data_dir / "extensions"

    @property
    def skills_extensions_dir(self) -> Path:
        return self.extensions_dir / "skills"

    @property
    def agents_extensions_dir(self) -> Path:
        return self.extensions_dir / "agents"

    @property
    def workspace_dir(self) -> Path:
        return self.user_data_dir / "workspace"

    def resolved_secret_key_path(self) -> Path:
        if self.sebastian_secret_key_path:
            return Path(self.sebastian_secret_key_path).expanduser()
        return self.user_data_dir / "secret.key"


settings = Settings()


def ensure_data_dir() -> None:
    """Create required data directory structure (idempotent).

    Runs the layout-v2 migration first to upgrade legacy installs.
    """
    from sebastian.store.migration import migrate_layout_v2

    migrate_layout_v2(settings.data_dir)

    for sub in (
        settings.user_data_dir / "extensions" / "skills",
        settings.user_data_dir / "extensions" / "agents",
        settings.user_data_dir / "workspace",
        settings.logs_dir,
        settings.run_dir,
    ):
        sub.mkdir(parents=True, exist_ok=True)


__all__ = ["Settings", "settings", "ensure_data_dir"]
