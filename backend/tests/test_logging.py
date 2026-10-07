import json
import logging
import sys

from app.logging_config import (
    REDACTED,
    RedactingConsoleFormatter,
    RedactingJsonFormatter,
    SecretRedactor,
)
from tests.fakes import (
    FAKE_BEARER_TOKEN,
    FAKE_GOOGLE_KEY,
    FAKE_LANGSMITH_KEY,
    FAKE_OPENAI_KEY,
)


def make_record(message: str, *args: object, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, args, None)
    record.__dict__.update(extra)
    return record


def test_redacts_configured_secret_values() -> None:
    redactor = SecretRedactor(["my-spotify-secret-value"])

    assert redactor.redact("token=my-spotify-secret-value;") == f"token={REDACTED};"


def test_redacts_known_key_shapes_without_configuration() -> None:
    redactor = SecretRedactor()
    text = (
        f"openai {FAKE_OPENAI_KEY} "
        f"langsmith {FAKE_LANGSMITH_KEY} "
        f"google {FAKE_GOOGLE_KEY} "
        f"header Authorization: Bearer {FAKE_BEARER_TOKEN}"
    )

    redacted = redactor.redact(text)

    for fake in (FAKE_OPENAI_KEY, FAKE_LANGSMITH_KEY, FAKE_GOOGLE_KEY, FAKE_BEARER_TOKEN):
        assert fake not in redacted
    assert redacted.count(REDACTED) == 4


def test_short_secret_values_are_not_redacted_by_value() -> None:
    # A 3-character "secret" would otherwise mask ordinary words in every log line.
    assert SecretRedactor(["abc"]).redact("abc") == "abc"


def test_json_formatter_outputs_fields_and_extras() -> None:
    formatter = RedactingJsonFormatter(SecretRedactor(["super-secret-value"]))
    record = make_record("GET %s %s", "/api/meta", 200, request_id="r1", duration_ms=1.5)

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "test"
    assert payload["message"] == "GET /api/meta 200"
    assert payload["request_id"] == "r1"
    assert payload["duration_ms"] == 1.5
    assert payload["timestamp"].endswith("+00:00")


def test_json_formatter_redacts_message_extras_and_exceptions() -> None:
    formatter = RedactingJsonFormatter(SecretRedactor(["super-secret-value"]))
    try:
        raise ValueError("failed with super-secret-value")
    except ValueError:
        record = make_record("key %s", "super-secret-value", header="Bearer abcdefghijkl")
        record.exc_info = sys.exc_info()

    line = formatter.format(record)

    assert "super-secret-value" not in line
    assert "abcdefghijkl" not in line
    assert "ValueError" in json.loads(line)["exception"]


def test_console_formatter_appends_extras_and_redacts() -> None:
    formatter = RedactingConsoleFormatter(SecretRedactor(["super-secret-value"]))
    record = make_record("using super-secret-value", request_id="r1")

    line = formatter.format(record)

    assert line.endswith(f"test: using {REDACTED} request_id=r1")


def test_uvicorn_color_message_is_dropped() -> None:
    formatter = RedactingJsonFormatter(SecretRedactor())
    record = make_record("Started server process", color_message="\x1b[36mStarted\x1b[0m")

    assert "color_message" not in json.loads(formatter.format(record))
