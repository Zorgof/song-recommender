"""Choose the STT provider from the settings."""

from app.config import Settings
from app.stt.base import STTProvider
from app.stt.openai_stt import OpenAISTT


def build_stt_provider(settings: Settings) -> STTProvider | None:
    """The configured provider, or None when STT is disabled (STT_PROVIDER=none or no key)."""
    if not settings.stt_enabled:
        return None
    match settings.stt_provider:
        case "openai":
            return OpenAISTT.from_settings(settings)
        case "none":
            return None
