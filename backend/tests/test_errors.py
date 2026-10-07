import io
import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.errors import LLMUnavailableError, NotFoundError
from tests.fakes import FAKE_OPENAI_KEY


class Payload(BaseModel):
    text: str = Field(min_length=3)


@pytest.fixture
def error_client(app: FastAPI) -> Iterator[TestClient]:
    @app.get("/api/_test/not-found")
    async def not_found() -> None:
        raise NotFoundError("Recommendation abc was not found.")

    @app.get("/api/_test/llm-down")
    async def llm_down() -> None:
        raise LLMUnavailableError()

    @app.get("/api/_test/crash")
    async def crash() -> None:
        raise RuntimeError(f"boom with {FAKE_OPENAI_KEY}")

    @app.post("/api/_test/validate")
    async def validate(payload: Payload) -> Payload:
        return payload

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_app_error_uses_shared_shape(error_client: TestClient) -> None:
    response = error_client.get("/api/_test/not-found")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Recommendation abc was not found."}
    }


def test_app_error_default_message(error_client: TestClient) -> None:
    response = error_client.get("/api/_test/llm-down")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "llm_unavailable",
        "message": "The language model provider is unavailable.",
    }


def test_unknown_route(error_client: TestClient) -> None:
    response = error_client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_wrong_method(error_client: TestClient) -> None:
    response = error_client.delete("/api/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_validation_error_does_not_echo_input(error_client: TestClient) -> None:
    response = error_client.post("/api/_test/validate", json={"text": "hi"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["body", "text"]
    assert "input" not in error["details"][0]


def test_unhandled_error_is_generic_and_logged_redacted(error_client: TestClient) -> None:
    # Redirect the handler installed by configure_logging(), keeping its redacting formatter.
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    stream = io.StringIO()
    handler.setStream(stream)

    response = error_client.get("/api/_test/crash")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "An unexpected error occurred."}
    }
    logs = stream.getvalue()
    assert "Unhandled error" in logs
    assert "RuntimeError" in logs
    assert FAKE_OPENAI_KEY not in logs
    assert "[REDACTED]" in logs
