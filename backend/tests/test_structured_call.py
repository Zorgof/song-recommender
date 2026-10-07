from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import pytest
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

from app.errors import LLMInvalidOutputError, LLMUnavailableError
from app.llm.models import ModelOptions, ModelRegistry, ModelSpec
from app.llm.structured import ESCALATION_INVALID_OUTPUT, structured_call
from tests.conftest import make_app_settings
from tests.fake_llm import ScriptedChatModel


class Mood(BaseModel):
    label: Literal["calm", "energetic"]
    intensity: float = Field(ge=0, le=1)


VALID = {"label": "calm", "intensity": 0.4}
INVALID = {"label": "sleepy", "intensity": 7}  # not in the Literal, out of range
PROMPT = "I had a long day and want to slow down."


def make_registry(
    tmp_path: Path, models: dict[str, ScriptedChatModel], **settings: Any
) -> ModelRegistry:
    """Registry whose factory returns the scripted model registered under the model name."""

    def factory(spec: ModelSpec, _: ModelOptions) -> BaseChatModel:
        return models[spec.model]

    config = {"llm_light": "openai:light", "llm_heavy": "openai:heavy", **settings}
    return ModelRegistry(make_app_settings(tmp_path, **config), factory)


async def test_light_tier_success(tmp_path: Path) -> None:
    light = ScriptedChatModel(model_name="light-v1", script=[VALID])
    heavy = ScriptedChatModel(model_name="heavy-v1", script=[VALID])
    registry = make_registry(tmp_path, {"light": light, "heavy": heavy})

    result = await structured_call(registry, "light", Mood, PROMPT)

    assert result.value == Mood(label="calm", intensity=0.4)
    assert (result.tier_requested, result.tier_used) == ("light", "light")
    assert result.model == "light-v1"
    assert result.escalated is False
    assert result.escalation_reason is None
    assert heavy.call_count == 0


async def test_heavy_tier_is_used_when_requested(tmp_path: Path) -> None:
    light = ScriptedChatModel(model_name="light-v1", script=[VALID])
    heavy = ScriptedChatModel(model_name="heavy-v1", script=[VALID])
    registry = make_registry(tmp_path, {"light": light, "heavy": heavy})

    result = await structured_call(registry, "heavy", Mood, PROMPT)

    assert result.tier_used == "heavy"
    assert result.model == "heavy-v1"
    assert light.call_count == 0


async def test_invalid_light_output_escalates_to_heavy(tmp_path: Path) -> None:
    light = ScriptedChatModel(model_name="light-v1", script=[INVALID])
    heavy = ScriptedChatModel(model_name="heavy-v1", script=[VALID])
    registry = make_registry(tmp_path, {"light": light, "heavy": heavy})

    result = await structured_call(registry, "light", Mood, PROMPT)

    assert result.value.label == "calm"
    assert (result.tier_requested, result.tier_used) == ("light", "heavy")
    assert result.escalated is True
    assert result.escalation_reason == ESCALATION_INVALID_OUTPUT
    assert (light.call_count, heavy.call_count) == (1, 1)


async def test_missing_fields_count_as_invalid_output(tmp_path: Path) -> None:
    light = ScriptedChatModel(model_name="light-v1", script=[{"label": "calm"}])
    heavy = ScriptedChatModel(model_name="heavy-v1", script=[VALID])
    registry = make_registry(tmp_path, {"light": light, "heavy": heavy})

    result = await structured_call(registry, "light", Mood, PROMPT)

    assert result.escalated is True


async def test_invalid_output_after_escalation_raises(tmp_path: Path) -> None:
    light = ScriptedChatModel(model_name="light-v1", script=[INVALID])
    heavy = ScriptedChatModel(model_name="heavy-v1", script=[INVALID])
    registry = make_registry(tmp_path, {"light": light, "heavy": heavy})

    with pytest.raises(LLMInvalidOutputError):
        await structured_call(registry, "light", Mood, PROMPT)

    assert (light.call_count, heavy.call_count) == (1, 1)


async def test_invalid_heavy_output_is_not_retried(tmp_path: Path) -> None:
    light = ScriptedChatModel(model_name="light-v1", script=[VALID])
    heavy = ScriptedChatModel(model_name="heavy-v1", script=[INVALID])
    registry = make_registry(tmp_path, {"light": light, "heavy": heavy})

    with pytest.raises(LLMInvalidOutputError):
        await structured_call(registry, "heavy", Mood, PROMPT)

    assert (light.call_count, heavy.call_count) == (0, 1)


async def test_provider_error_uses_fallback_model(tmp_path: Path) -> None:
    light = ScriptedChatModel(model_name="light-v1", script=[RuntimeError("503 from provider")])
    backup = ScriptedChatModel(model_name="backup-v1", script=[VALID])
    heavy = ScriptedChatModel(model_name="heavy-v1", script=[VALID])
    registry = make_registry(
        tmp_path,
        {"light": light, "backup": backup, "heavy": heavy},
        llm_light_fallback="openai:backup",
    )

    result = await structured_call(registry, "light", Mood, PROMPT)

    assert result.model == "backup-v1"
    assert result.tier_used == "light"
    assert result.escalated is False
    assert (light.call_count, backup.call_count, heavy.call_count) == (1, 1, 0)


async def test_provider_error_without_fallback_is_unavailable(tmp_path: Path) -> None:
    light = ScriptedChatModel(model_name="light-v1", script=[RuntimeError("503 from provider")])
    heavy = ScriptedChatModel(model_name="heavy-v1", script=[VALID])
    registry = make_registry(tmp_path, {"light": light, "heavy": heavy})

    with pytest.raises(LLMUnavailableError):
        await structured_call(registry, "light", Mood, PROMPT)

    # Provider errors are not an output-quality problem: no escalation to the heavy tier.
    assert heavy.call_count == 0


async def test_failing_primary_and_fallback_is_unavailable(tmp_path: Path) -> None:
    light = ScriptedChatModel(model_name="light-v1", script=[RuntimeError("down")])
    backup = ScriptedChatModel(model_name="backup-v1", script=[RuntimeError("down too")])
    heavy = ScriptedChatModel(model_name="heavy-v1", script=[VALID])
    registry = make_registry(
        tmp_path,
        {"light": light, "backup": backup, "heavy": heavy},
        llm_light_fallback="openai:backup",
    )

    with pytest.raises(LLMUnavailableError):
        await structured_call(registry, "light", Mood, PROMPT)


class MetadataRecorder(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.seen: list[tuple[dict[str, Any], list[str]]] = []

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.seen.append((metadata or {}, tags or []))


async def test_tier_and_escalation_are_recorded_for_tracing(tmp_path: Path) -> None:
    light = ScriptedChatModel(model_name="light-v1", script=[INVALID])
    heavy = ScriptedChatModel(model_name="heavy-v1", script=[VALID])
    registry = make_registry(tmp_path, {"light": light, "heavy": heavy})
    recorder = MetadataRecorder()

    await structured_call(
        registry,
        "light",
        Mood,
        PROMPT,
        config={"callbacks": [recorder], "metadata": {"node": "need_analyst"}, "tags": ["t"]},
    )

    (first_meta, first_tags), (second_meta, second_tags) = recorder.seen
    assert first_meta["node"] == "need_analyst"
    assert (first_meta["tier"], first_meta["escalated"]) == ("light", False)
    assert (second_meta["tier"], second_meta["escalated"]) == ("heavy", True)
    assert second_meta["escalation_reason"] == ESCALATION_INVALID_OUTPUT
    # LangChain adds its own internal tags (e.g. "map:key:raw") to nested runs.
    assert {"t", "tier:light"} <= set(first_tags)
    assert "tier:heavy" not in first_tags
    assert {"t", "tier:heavy"} <= set(second_tags)
