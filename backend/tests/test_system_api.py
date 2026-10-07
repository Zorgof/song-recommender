import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import __version__
from app.api.deps import get_session
from app.config import Settings
from app.main import create_app
from tests.conftest import make_settings


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_unreachable_database(app: FastAPI) -> None:
    class BrokenSession:
        async def execute(self, *_: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("disk I/O error"))

    async def broken_session() -> AsyncIterator[BrokenSession]:
        yield BrokenSession()

    app.dependency_overrides[get_session] = broken_session
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "error"}


def test_startup_creates_database_with_schema(settings: Settings, client: TestClient) -> None:
    assert settings.database_path.is_file()
    with sqlite3.connect(settings.database_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in rows}
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()

    assert {"recommendations", "feedback", "track_link_cache"} <= tables
    assert version == ("0001",)


def test_startup_is_idempotent(settings: Settings) -> None:
    for _ in range(2):
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/health").status_code == 200


def test_request_id_is_generated_or_propagated(client: TestClient) -> None:
    generated = client.get("/api/health").headers["X-Request-ID"]
    propagated = client.get("/api/health", headers={"X-Request-ID": "abc-123"})

    assert len(generated) == 32
    assert propagated.headers["X-Request-ID"] == "abc-123"


def test_meta_with_nothing_configured(client: TestClient) -> None:
    body = client.get("/api/meta").json()

    assert body == {
        "app": {"name": "song-recommender", "version": __version__, "environment": "development"},
        "llm": {
            "light": None,
            "heavy": None,
            "light_fallback": None,
            "heavy_fallback": None,
            "heavy_reasoning": False,
        },
        "stt": {"enabled": False, "provider": "openai"},
        "catalogs": {"spotify": False, "youtube": False},
        "langsmith": {"enabled": False, "project": None},
        "locales": ["en", "pl"],
    }


def test_meta_reports_configuration_without_leaking_secrets(tmp_path: Path) -> None:
    secrets = {
        "openai_api_key": "test-openai-key-0123456789",
        "spotify_client_secret": "test-spotify-secret-0123456789",
        "youtube_api_key": "test-youtube-key-0123456789",
        "langsmith_api_key": "test-langsmith-key-0123456789",
    }
    settings = make_settings(
        tmp_path,
        llm_light="openai:light-model",
        llm_heavy="openai:heavy-model",
        spotify_client_id="spotify-client-id",
        langsmith_tracing=True,
        **secrets,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/meta")

    body = response.json()
    assert body["llm"]["light"] == "openai:light-model"
    assert body["stt"] == {"enabled": True, "provider": "openai"}
    assert body["catalogs"] == {"spotify": True, "youtube": True}
    assert body["langsmith"] == {"enabled": True, "project": "song-recommender"}
    for secret in secrets.values():
        assert secret not in response.text


def test_openapi_docs_are_served_under_api(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/docs").status_code == 200


def test_cors_only_in_development(tmp_path: Path) -> None:
    preflight = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    }
    dev = TestClient(create_app(make_settings(tmp_path, app_env="development")))
    prod = TestClient(create_app(make_settings(tmp_path, app_env="production")))

    dev_response = dev.options("/api/meta", headers=preflight)
    prod_response = prod.options("/api/meta", headers=preflight)

    assert dev_response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in prod_response.headers
