from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.config import REPO_ROOT, Settings
from tests.conftest import make_settings


def test_defaults(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    assert settings.app_env == "development"
    assert settings.llm_light is None
    assert settings.stt_provider == "openai"
    assert settings.spotify_market == "PL"
    assert settings.langsmith_endpoint == "https://api.smith.langchain.com"
    assert settings.langsmith_workspace_id is None
    assert settings.database_url == f"sqlite+aiosqlite:///{tmp_path / 'data' / 'app.db'}"


def test_reads_env_file_and_treats_empty_values_as_unset(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment line\n"
        "LLM_LIGHT=\n"
        "LLM_HEAVY=openai:some-model\n"
        "LLM_HEAVY_REASONING=on\n"
        "OPENAI_API_KEY=test-openai-key-value\n"
        "APP_PORT=8080\n"
    )

    settings = Settings(_env_file=env_file)

    assert settings.llm_light is None
    assert settings.llm_heavy == "openai:some-model"
    assert settings.llm_heavy_reasoning is True
    assert settings.openai_api_key == SecretStr("test-openai-key-value")


def test_environment_overrides_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=DEBUG\n")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    assert Settings(_env_file=env_file).log_level == "WARNING"


@pytest.mark.parametrize("market", ["pl", "POL", ""])
def test_rejects_invalid_spotify_market(tmp_path: Path, market: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(tmp_path, spotify_market=market)


def test_secrets_are_hidden_in_repr(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, openai_api_key="test-secret-value-123456")

    assert "test-secret-value-123456" not in repr(settings)
    assert settings.secret_values() == ["test-secret-value-123456"]


def test_stt_enabled_requires_openai_key(tmp_path: Path) -> None:
    assert make_settings(tmp_path).stt_enabled is False
    assert make_settings(tmp_path, openai_api_key="test-key").stt_enabled is True
    assert (
        make_settings(tmp_path, openai_api_key="test-key", stt_provider="none").stt_enabled is False
    )


def test_langsmith_enabled_requires_flag_and_key(tmp_path: Path) -> None:
    assert make_settings(tmp_path, langsmith_tracing=True).langsmith_enabled is False
    assert make_settings(tmp_path, langsmith_api_key="test-key").langsmith_enabled is False
    enabled = make_settings(tmp_path, langsmith_tracing=True, langsmith_api_key="test-key")
    assert enabled.langsmith_enabled is True


def test_catalog_flags(tmp_path: Path) -> None:
    assert make_settings(tmp_path, spotify_client_id="id").spotify_configured is False
    assert (
        make_settings(
            tmp_path, spotify_client_id="id", spotify_client_secret="secret"
        ).spotify_configured
        is True
    )
    assert make_settings(tmp_path, youtube_api_key="test-key").youtube_configured is True


def test_env_example_is_a_valid_configuration() -> None:
    env_example = REPO_ROOT / ".env.example"

    settings = Settings(_env_file=env_example)

    assert settings.llm_heavy_reasoning is False
    assert settings.langsmith_tracing is True
    assert settings.openai_api_key is None  # empty placeholders are treated as unset
    assert settings.cors_origins == ["http://localhost:5173"]
