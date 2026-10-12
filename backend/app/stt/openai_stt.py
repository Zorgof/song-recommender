"""OpenAI transcription (`/v1/audio/transcriptions`) with the shared OPENAI_API_KEY (FR-31).

Only the `json` response format is used, as it is the one every transcription model supports.
`gpt-transcribe` returns the detected languages in it; models billed per audio minute report
the duration in `usage`. Fields a model does not return are left as None.
"""

import logging

import openai
from openai.types.audio import Transcription, TranscriptionCreateResponse

from app.config import Settings
from app.errors import BudgetExhaustedError, InvalidAudioError, STTUnavailableError
from app.llm.budget import is_budget_exhausted
from app.stt.base import AUDIO_FORMATS, Transcript

logger = logging.getLogger(__name__)


class OpenAISTT:
    name = "openai"

    def __init__(self, client: openai.AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAISTT:
        assert settings.openai_api_key is not None
        client = openai.AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        return cls(client, settings.stt_model)

    async def transcribe(self, audio: bytes, mime: str) -> Transcript:
        # The API identifies the format from the file name and content type.
        file = (f"recording.{AUDIO_FORMATS[mime]}", audio, mime)
        try:
            result = await self._client.audio.transcriptions.create(model=self._model, file=file)
        except openai.BadRequestError as exc:
            if exc.param == "file":
                # Corrupted, unsupported or too short audio.
                logger.warning("OpenAI rejected the audio", extra={"code": exc.code, "mime": mime})
                raise InvalidAudioError() from exc
            logger.error("OpenAI transcription request was rejected", extra=_error_extra(exc))
            raise STTUnavailableError() from exc
        except openai.APIError as exc:
            logger.error("OpenAI transcription failed", extra=_error_extra(exc))
            if is_budget_exhausted(exc):
                raise BudgetExhaustedError() from exc
            raise STTUnavailableError() from exc
        return Transcript(
            text=result.text.strip(), language=_language(result), duration_s=_duration(result)
        )

    async def aclose(self) -> None:
        await self._client.close()


def _language(result: TranscriptionCreateResponse) -> str | None:
    if isinstance(result, Transcription) and result.languages:
        return result.languages[0].code.lower()
    return None


def _duration(result: TranscriptionCreateResponse) -> float | None:
    usage = getattr(result, "usage", None)
    if usage is not None and usage.type == "duration":
        return float(usage.seconds)
    return None


def _error_extra(exc: openai.APIError) -> dict[str, object]:
    # The message is not logged: it may quote request details.
    return {
        "error": type(exc).__name__,
        "status": getattr(exc, "status_code", None),
        "code": exc.code,
    }
