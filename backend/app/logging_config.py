"""Logging setup: JSON lines in production, readable lines in development, secrets redacted."""

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from app.config import Settings

REDACTED = "[REDACTED]"

# Shapes of common credentials, redacted even if they are not part of the settings.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI / Anthropic keys
    re.compile(r"lsv2_[A-Za-z0-9_]{16,}"),  # LangSmith keys
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),  # Google API keys
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),  # Authorization headers
)

# Attributes every LogRecord has; anything else was passed via `extra=` and is logged as a field.
# `color_message` is uvicorn's ANSI-colored copy of the message: noise in both formats.
_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
    | {"message", "asctime", "color_message"}
)

# Secret values shorter than this are not redacted by value, to avoid masking common words.
_MIN_SECRET_LENGTH = 8


class SecretRedactor:
    def __init__(self, secret_values: Iterable[str] = ()) -> None:
        # Longest first, so a secret that contains another one is replaced as a whole.
        self._values = sorted(
            {v for v in secret_values if len(v) >= _MIN_SECRET_LENGTH}, key=len, reverse=True
        )

    def redact(self, text: str) -> str:
        for value in self._values:
            text = text.replace(value, REDACTED)
        for pattern in SECRET_PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k not in _STANDARD_RECORD_ATTRS}


class RedactingJsonFormatter(logging.Formatter):
    """One JSON object per line; `extra=` fields become top-level keys."""

    def __init__(self, redactor: SecretRedactor) -> None:
        super().__init__()
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_extra_fields(record),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return self._redactor.redact(json.dumps(payload, default=str, ensure_ascii=False))


class RedactingConsoleFormatter(logging.Formatter):
    """Human-readable lines for development; `extra=` fields are appended as key=value."""

    def __init__(self, redactor: SecretRedactor) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = _extra_fields(record)
        if extras:
            line += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        return self._redactor.redact(line)


def configure_logging(settings: Settings) -> None:
    redactor = SecretRedactor(settings.secret_values())
    formatter: logging.Formatter = (
        RedactingConsoleFormatter(redactor)
        if settings.is_development
        else RedactingJsonFormatter(redactor)
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Route uvicorn's loggers through the root handler; request logging is done by our middleware.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
