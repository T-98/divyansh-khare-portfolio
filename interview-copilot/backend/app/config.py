"""Runtime configuration.

Every model name is configurable. The defaults follow the build spec; if an
account does not have access to those IDs, override them in `.env` — nothing in
the architecture depends on a specific model.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""

    router_model: str = "gpt-5.6-luna"
    specialist_model: str = "gpt-5.6-terra"
    editor_model: str = "gpt-5.6-terra"
    deep_model: str = "gpt-5.6-sol"
    transcribe_model: str = "gpt-4o-transcribe"

    # Used only when a configured model ID is rejected by the API
    # (model_not_found / unsupported). Keeps the app usable on any account.
    fallback_model: str = "gpt-4.1"
    fallback_transcribe_model: str = "whisper-1"

    database_url: str = "sqlite+aiosqlite:///./interview.db"
    cors_origins: str = "http://localhost:5173"
    debug_agent_output: bool = False

    # Live interview: fail fast rather than hang.
    router_timeout_s: float = 8.0
    specialist_timeout_s: float = 45.0
    editor_timeout_s: float = 60.0
    transcribe_timeout_s: float = 45.0

    max_transcribe_bytes: int = 25 * 1024 * 1024
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlite_path(self) -> str:
        """Extract a plain filesystem path from a SQLAlchemy-style URL.

        We do not use SQLAlchemy — the URL form is kept so the same env var can
        point at Postgres later without a config migration.
        """
        url = self.database_url
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if url.startswith(prefix):
                return url[len(prefix) :] or ":memory:"
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
