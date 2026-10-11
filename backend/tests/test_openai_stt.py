"""OpenAISTT against a mocked OpenAI HTTP API (the openai SDK uses httpx2)."""

from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx2
import openai
import pytest

from app.errors import InvalidAudioError, STTUnavailableError
from app.stt.base import Transcript
from app.stt.factory import build_stt_provider
from app.stt.openai_stt import OpenAISTT
from tests.conftest import make_settings
from tests.fakes import FAKE_OPENAI_KEY

AUDIO = b"\x1aE\xdf\xa3 fake webm"
Handler = Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]]


def make_stt(handler: Handler, model: str = "gpt-transcribe") -> OpenAISTT:
    client = openai.AsyncOpenAI(
        api_key=FAKE_OPENAI_KEY,
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return OpenAISTT(client, model)


def reply(status: int, body: dict[str, Any]) -> Handler:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        return httpx2.Response(status, json=body)

    return handler


def api_error(param: str | None, code: str = "invalid_value") -> dict[str, Any]:
    return {
        "error": {
            "message": "Something is wrong.",
            "type": "invalid_request_error",
            "param": param,
            "code": code,
        }
    }


async def test_transcribes_with_detected_language_and_duration() -> None:
    requests: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "text": "  Miałem ciężki dzień.  ",
                "languages": [{"code": "PL"}, {"code": "en"}],
                "usage": {"type": "duration", "seconds": 4.2},
            },
        )

    transcript = await make_stt(handler).transcribe(AUDIO, "audio/webm")

    assert transcript == Transcript(text="Miałem ciężki dzień.", language="pl", duration_s=4.2)
    (request,) = requests
    assert request.method == "POST"
    assert request.url.path == "/v1/audio/transcriptions"
    body = request.content
    assert b'name="model"\r\n\r\ngpt-transcribe' in body
    assert b'filename="recording.webm"' in body
    assert b"Content-Type: audio/webm" in body
    assert AUDIO in body
    # The language is detected by the model, never forced from the UI locale.
    assert b'name="language' not in body


async def test_fields_the_model_does_not_return_are_none() -> None:
    usage = {"type": "tokens", "input_tokens": 10, "output_tokens": 3, "total_tokens": 13}
    stt = make_stt(reply(200, {"text": "Long day.", "usage": usage}), "gpt-4o-mini-transcribe")

    transcript = await stt.transcribe(AUDIO, "audio/ogg")

    assert transcript == Transcript(text="Long day.", language=None, duration_s=None)


async def test_no_reliable_language_gives_none() -> None:
    stt = make_stt(reply(200, {"text": "", "languages": []}))

    assert await stt.transcribe(AUDIO, "audio/mp4") == Transcript("", None, None)


async def test_audio_rejected_by_openai_is_invalid_audio() -> None:
    stt = make_stt(reply(400, api_error("file", "audio_too_short")))

    with pytest.raises(InvalidAudioError):
        await stt.transcribe(AUDIO, "audio/wav")


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (400, api_error("model")),  # e.g. a wrong STT_MODEL
        (401, api_error(None, "invalid_api_key")),
        (429, api_error(None, "rate_limit_exceeded")),
        (500, api_error(None, "server_error")),
    ],
    ids=["bad-request", "auth", "rate-limit", "server-error"],
)
async def test_provider_errors_are_stt_unavailable(status: int, body: dict[str, Any]) -> None:
    stt = make_stt(reply(status, body))

    with pytest.raises(STTUnavailableError):
        await stt.transcribe(AUDIO, "audio/webm")


async def test_network_error_is_stt_unavailable() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("unreachable", request=request)

    with pytest.raises(STTUnavailableError):
        await make_stt(handler).transcribe(AUDIO, "audio/webm")


async def test_aclose_closes_the_http_client() -> None:
    stt = make_stt(reply(200, {"text": "x"}))

    await stt.aclose()

    assert stt._client.is_closed()


def test_factory_builds_openai_stt_from_settings(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, openai_api_key=FAKE_OPENAI_KEY, stt_model="whisper-1")

    stt = build_stt_provider(settings)

    assert isinstance(stt, OpenAISTT)
    assert stt._model == "whisper-1"


@pytest.mark.parametrize(
    "overrides",
    [{}, {"openai_api_key": FAKE_OPENAI_KEY, "stt_provider": "none"}],
    ids=["no-key", "provider-none"],
)
def test_factory_returns_none_when_stt_is_disabled(
    tmp_path: Path, overrides: dict[str, Any]
) -> None:
    assert build_stt_provider(make_settings(tmp_path, **overrides)) is None
