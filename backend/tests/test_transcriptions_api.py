"""POST /api/transcriptions with a fake STT provider."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.transcriptions import MAX_AUDIO_BYTES
from app.errors import AppError, InvalidAudioError, STTUnavailableError
from app.main import create_app
from app.stt.base import Transcript
from app.stt.openai_stt import OpenAISTT
from tests.conftest import make_app_settings

AUDIO = b"\x1aE\xdf\xa3 fake webm"


class FakeSTT:
    name = "fake"

    def __init__(self, transcript: Transcript | None = None, error: AppError | None = None) -> None:
        self.transcript = transcript or Transcript("Long day at work.", "en", 3.5)
        self.error = error
        self.calls: list[tuple[bytes, str]] = []

    async def transcribe(self, audio: bytes, mime: str) -> Transcript:
        self.calls.append((audio, mime))
        if self.error is not None:
            raise self.error
        return self.transcript

    async def aclose(self) -> None:
        pass


@pytest.fixture
def stt(client: TestClient, app: FastAPI) -> FakeSTT:
    fake = FakeSTT()
    app.state.stt = fake
    return fake


def upload(
    client: TestClient, data: bytes = AUDIO, content_type: str = "audio/webm;codecs=opus"
) -> Any:
    return client.post(
        "/api/transcriptions", files={"audio": ("recording.webm", data, content_type)}
    )


def test_returns_the_transcript(client: TestClient, stt: FakeSTT) -> None:
    response = upload(client)

    assert response.status_code == 200, response.text
    assert response.json() == {"text": "Long day at work.", "language": "en", "duration_s": 3.5}
    # The codecs parameter is dropped; the provider gets the base content type.
    assert stt.calls == [(AUDIO, "audio/webm")]


@pytest.mark.parametrize(
    "content_type", ["audio/ogg", "audio/mp4", "audio/wav", "audio/x-wav", "AUDIO/WEBM"]
)
def test_accepts_browser_recording_formats(
    client: TestClient, stt: FakeSTT, content_type: str
) -> None:
    assert upload(client, content_type=content_type).status_code == 200


def test_empty_transcript_is_not_an_error(client: TestClient, stt: FakeSTT) -> None:
    stt.transcript = Transcript("", None, None)

    response = upload(client)

    assert response.status_code == 200
    assert response.json() == {"text": "", "language": None, "duration_s": None}


@pytest.mark.parametrize(
    ("data", "content_type", "status", "code"),
    [
        (AUDIO, "text/plain", 415, "unsupported_audio_format"),
        (AUDIO, "video/x-msvideo", 415, "unsupported_audio_format"),
        (b"", "audio/webm", 422, "invalid_audio"),
        (b"x" * (MAX_AUDIO_BYTES + 1), "audio/webm", 413, "audio_too_large"),
    ],
    ids=["text", "video", "empty", "too-large"],
)
def test_rejects_invalid_uploads_before_calling_the_provider(
    client: TestClient, stt: FakeSTT, data: bytes, content_type: str, status: int, code: str
) -> None:
    response = upload(client, data, content_type)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert stt.calls == []


def test_accepts_exactly_the_size_limit(client: TestClient, stt: FakeSTT) -> None:
    assert upload(client, b"x" * MAX_AUDIO_BYTES).status_code == 200


def test_missing_audio_field_is_a_validation_error(client: TestClient, stt: FakeSTT) -> None:
    response = client.post("/api/transcriptions", data={"other": "x"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [(InvalidAudioError(), 422, "invalid_audio"), (STTUnavailableError(), 503, "stt_unavailable")],
)
def test_provider_errors_use_the_error_shape(
    client: TestClient, stt: FakeSTT, error: AppError, status: int, code: str
) -> None:
    stt.error = error

    response = upload(client)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_disabled_stt_is_unavailable(tmp_path: Path) -> None:
    app = create_app(make_app_settings(tmp_path, stt_provider="none"))
    with TestClient(app) as client:
        assert app.state.stt is None
        assert client.get("/api/meta").json()["stt"] == {
            "enabled": False,
            "provider": "none",
            "model": None,
        }

        response = upload(client)

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "stt_unavailable",
        "message": "Speech-to-text is disabled.",
    }


def test_app_uses_openai_stt_when_configured(client: TestClient, app: FastAPI) -> None:
    assert isinstance(app.state.stt, OpenAISTT)


def test_transcript_is_not_logged(
    client: TestClient, stt: FakeSTT, caplog: pytest.LogCaptureFixture
) -> None:
    stt.transcript = Transcript("very private words", "en", 2.0)

    with caplog.at_level("INFO"):
        assert upload(client).status_code == 200

    (record,) = [r for r in caplog.records if r.getMessage() == "Recording transcribed"]
    assert record.__dict__["language"] == "en"
    assert "very private words" not in caplog.text
