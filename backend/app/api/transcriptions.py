"""Speech-to-text endpoint: one recorded clip in, its transcript out (FR-2, FR-3).

The audio goes only to the STT provider: it is neither stored nor traced (NFR-5). The
transcript reaches LangSmith with the recommendation request it is submitted with.
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.api.deps import STTDep
from app.api.transcription_schemas import TranscriptionResponse
from app.errors import AudioTooLargeError, InvalidAudioError, UnsupportedAudioFormatError
from app.stt.base import AUDIO_FORMATS, base_content_type

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcriptions", tags=["transcriptions"])

# FR-6: a voice recording is at most 90 s or 10 MB.
MAX_AUDIO_BYTES = 10 * 1024 * 1024


@router.post("")
async def create_transcription(
    audio: Annotated[UploadFile, File(description="The recording: webm, ogg, mp4 or wav.")],
    stt: STTDep,
) -> TranscriptionResponse:
    """Transcribe a recording. The language is detected, not taken from the UI locale."""
    mime = base_content_type(audio.content_type)
    if mime not in AUDIO_FORMATS:
        supported = ", ".join(AUDIO_FORMATS)
        raise UnsupportedAudioFormatError(
            f"The recording format is not supported. Supported: {supported}."
        )
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise AudioTooLargeError(
            f"The recording is larger than {MAX_AUDIO_BYTES // (1024 * 1024)} MB."
        )
    if not data:
        raise InvalidAudioError("The recording is empty.")

    started = time.perf_counter()
    transcript = await stt.transcribe(data, mime)
    # The transcript itself is not logged (privacy).
    logger.info(
        "Recording transcribed",
        extra={
            "provider": stt.name,
            "mime": mime,
            "size_bytes": len(data),
            "language": transcript.language,
            "duration_s": transcript.duration_s,
            "chars": len(transcript.text),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return TranscriptionResponse(
        text=transcript.text, language=transcript.language, duration_s=transcript.duration_s
    )
