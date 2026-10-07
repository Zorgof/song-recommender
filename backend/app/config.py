"""Application settings loaded from environment variables and the repository `.env` file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[2]

AppEnv = Literal["development", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
SttProvider = Literal["openai", "none"]

SUPPORTED_LOCALES: tuple[str, ...] = ("en", "pl")


class Settings(BaseSettings):
    """All runtime configuration. Field names map to upper-case env variables."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        # Treat `KEY=` lines from .env.example as "not set", so defaults and None apply.
        env_ignore_empty=True,
        # .env also holds variables for Docker Compose (e.g. APP_PORT).
        extra="ignore",
    )

    # --- Application ---
    app_env: AppEnv = "development"
    log_level: LogLevel = "INFO"
    data_dir: Path = Path("data")
    history_exclude_last_n: int = Field(default=50, ge=0)
    # Used only when app_env=development; in production nginx serves the SPA on the same origin.
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- LLM providers ---
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None

    # --- Model tiers (provider:model); validated in the LLM layer ---
    llm_light: str | None = None
    llm_heavy: str | None = None
    llm_light_fallback: str | None = None
    llm_heavy_fallback: str | None = None
    llm_heavy_reasoning: bool = False

    # --- Speech-to-text ---
    stt_provider: SttProvider = "openai"
    stt_model: str | None = None

    # --- Spotify ---
    spotify_client_id: str | None = None
    spotify_client_secret: SecretStr | None = None
    spotify_market: str = Field(default="PL", pattern=r"^[A-Z]{2}$")

    # --- YouTube ---
    youtube_api_key: SecretStr | None = None

    # --- LangSmith ---
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    # Required when the key is an organization-scoped service key (`lsv2_sk_…`): such keys must
    # name the workspace on every request. Optional for personal access tokens.
    langsmith_workspace_id: str | None = None
    langsmith_project: str = "song-recommender"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def stt_enabled(self) -> bool:
        if self.stt_provider == "openai":
            return self.openai_api_key is not None
        return False

    @property
    def langsmith_enabled(self) -> bool:
        return self.langsmith_tracing and self.langsmith_api_key is not None

    @property
    def spotify_configured(self) -> bool:
        return self.spotify_client_id is not None and self.spotify_client_secret is not None

    @property
    def youtube_configured(self) -> bool:
        return self.youtube_api_key is not None

    def secret_values(self) -> list[str]:
        """Plain values of every configured secret, used to redact them from logs."""
        values: list[str] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr):
                values.append(value.get_secret_value())
        return [v for v in values if v]


@lru_cache
def get_settings() -> Settings:
    return Settings()
