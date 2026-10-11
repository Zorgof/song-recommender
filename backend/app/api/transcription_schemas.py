"""Response schema of the transcription endpoint."""

from pydantic import BaseModel


class TranscriptionResponse(BaseModel):
    # Empty when no speech was recognized.
    text: str
    # ISO 639-1 code of the spoken language, when the provider detects it.
    language: str | None
    # Length of the recording in seconds, when the provider reports it.
    duration_s: float | None
