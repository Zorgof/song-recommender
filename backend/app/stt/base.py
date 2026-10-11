"""Speech-to-text interface (FR-30) and the audio formats accepted from the browser.

A provider turns one recorded clip into text. The language is detected by the provider: no hint
is passed, because the user may speak Polish with the UI in English (and the other way round).
"""

from dataclasses import dataclass
from typing import Protocol

# Content types accepted by POST /api/transcriptions (without parameters such as
# `;codecs=opus`), mapped to the file extension the provider identifies the format from.
# MediaRecorder produces webm (Chrome, Firefox), ogg (older Firefox) or mp4 (Safari).
AUDIO_FORMATS: dict[str, str] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}


def base_content_type(content_type: str | None) -> str:
    """`audio/webm;codecs=opus` -> `audio/webm`."""
    return (content_type or "").split(";", 1)[0].strip().lower()


@dataclass(frozen=True)
class Transcript:
    text: str
    # ISO 639-1 code of the detected language; None when the provider could not tell.
    language: str | None
    # Length of the audio in seconds; None when the provider does not report it.
    duration_s: float | None


class STTProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, mime: str) -> Transcript:
        """Transcribe one clip. `mime` is a key of AUDIO_FORMATS.

        Raises InvalidAudioError when the provider cannot decode the audio and
        STTUnavailableError when the provider cannot be used.
        """
        ...

    async def aclose(self) -> None: ...
