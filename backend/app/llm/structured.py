"""Structured LLM calls with validation and light → heavy escalation.

Two kinds of failure are handled differently:
- the provider fails (network, rate limit, 5xx after the SDK's own retries): the tier's fallback
  model is tried (see ModelRegistry.structured); if that fails too, LLMUnavailableError;
- the model answers but the output does not match the schema: on the light tier the call is
  repeated once on the heavy tier; on the heavy tier, LLMInvalidOutputError.
"""

import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from app.errors import LLMInvalidOutputError, LLMUnavailableError
from app.llm.models import ModelRegistry, Tier

logger = logging.getLogger(__name__)

ESCALATION_INVALID_OUTPUT = "invalid_structured_output"


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    tier_requested: Tier
    tier_used: Tier
    # Model name reported by the provider (e.g. a dated snapshot); the configured spec otherwise.
    model: str
    escalated: bool
    escalation_reason: str | None


async def structured_call[T: BaseModel](
    registry: ModelRegistry,
    tier: Tier,
    schema: type[T],
    messages: LanguageModelInput,
    *,
    config: RunnableConfig | None = None,
) -> StructuredResult[T]:
    attempt_tier: Tier = tier
    escalation_reason: str | None = None

    while True:
        runnable = registry.structured(attempt_tier, schema)
        attempt_config = _attempt_config(config, attempt_tier, escalation_reason)
        try:
            output: dict[str, Any] = await runnable.ainvoke(messages, config=attempt_config)
        except Exception as exc:
            logger.warning(
                "LLM call failed",
                extra={"tier": attempt_tier, "error_type": type(exc).__name__},
            )
            raise LLMUnavailableError() from exc

        parsed = output.get("parsed")
        if isinstance(parsed, schema) and output.get("parsing_error") is None:
            return StructuredResult(
                value=parsed,
                tier_requested=tier,
                tier_used=attempt_tier,
                model=_model_name(output.get("raw"), registry, attempt_tier),
                escalated=escalation_reason is not None,
                escalation_reason=escalation_reason,
            )

        logger.warning(
            "LLM returned invalid structured output",
            extra={
                "tier": attempt_tier,
                "schema": schema.__name__,
                "parsing_error": type(output.get("parsing_error")).__name__,
            },
        )
        if attempt_tier == "light":
            escalation_reason = ESCALATION_INVALID_OUTPUT
            attempt_tier = "heavy"
            continue
        raise LLMInvalidOutputError()


def _attempt_config(
    config: RunnableConfig | None, tier: Tier, escalation_reason: str | None
) -> RunnableConfig:
    """Copy of the caller's config with the tier and escalation recorded for LangSmith."""
    merged: RunnableConfig = {**(config or {})}
    merged["metadata"] = {
        **(merged.get("metadata") or {}),
        "tier": tier,
        "escalated": escalation_reason is not None,
        "escalation_reason": escalation_reason,
    }
    merged["tags"] = [*(merged.get("tags") or []), f"tier:{tier}"]
    return merged


def _model_name(raw: Any, registry: ModelRegistry, tier: Tier) -> str:
    if isinstance(raw, AIMessage):
        name = raw.response_metadata.get("model_name") or raw.response_metadata.get("model")
        if isinstance(name, str) and name:
            return name
    return str(registry.tier_config(tier).primary)
