from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.migrate import upgrade_to_head
from app.db.session import create_engine, create_session_factory
from app.main import create_app


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's shell environment out of the tests."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Settings that ignore the repository .env file and keep data in a temp directory."""
    values: dict[str, Any] = {"data_dir": tmp_path / "data", **overrides}
    return Settings(_env_file=None, **values)


# The smallest configuration the application starts with (see ModelRegistry validation).
MINIMAL_APP_CONFIG: dict[str, Any] = {
    "llm_light": "openai:test-light-model",
    "llm_heavy": "openai:test-heavy-model",
    "openai_api_key": "test-openai-key",
}


def make_app_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Like make_settings(), plus the minimal configuration needed by create_app()."""
    return make_settings(tmp_path, **{**MINIMAL_APP_CONFIG, **overrides})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_app_settings(tmp_path)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # The context manager runs the lifespan (migrations, engine).
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def session_factory(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    upgrade_to_head(settings.database_path)
    engine = create_engine(settings.database_url)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
