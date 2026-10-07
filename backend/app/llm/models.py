"""Model registry: maps the light/heavy tiers (`provider:model` settings) to LangChain chat models.

API keys are passed to every model explicitly from Settings: the provider SDKs would otherwise
look for them in os.environ, which does not contain the values that live only in `.env`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.runnables import Runnable
from pydantic import BaseModel, SecretStr

from app.config import Settings
from app.errors import ConfigurationError

Tier = Literal["light", "heavy"]
TIERS: tuple[Tier, ...] = ("light", "heavy")

# Used when LLM_HEAVY_REASONING=on.
REASONING_EFFORT = "medium"


class Provider(StrEnum):
    """Provider names as understood by LangChain's `init_chat_model`."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE_GENAI = "google_genai"


# Settings field holding each provider's key, and the env variable to name in error messages.
_PROVIDER_KEYS: dict[Provider, tuple[str, str]] = {
    Provider.OPENAI: ("openai_api_key", "OPENAI_API_KEY"),
    Provider.ANTHROPIC: ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    Provider.GOOGLE_GENAI: ("google_api_key", "GOOGLE_API_KEY"),
}


@dataclass(frozen=True)
class ModelSpec:
    provider: Provider
    model: str

    def __str__(self) -> str:
        return f"{self.provider.value}:{self.model}"


@dataclass(frozen=True)
class TierConfig:
    primary: ModelSpec
    fallback: ModelSpec | None


@dataclass(frozen=True)
class ModelOptions:
    api_key: str
    timeout_seconds: float
    max_retries: int
    reasoning: bool


ModelFactory = Callable[[ModelSpec, ModelOptions], BaseChatModel]


def parse_model_spec(value: str) -> ModelSpec:
    """Parse `provider:model`. Raises ValueError with a human-readable reason."""
    provider, sep, model = value.strip().partition(":")
    if not sep or not provider or not model:
        raise ValueError(f"'{value}' is not in the form provider:model")
    try:
        return ModelSpec(Provider(provider), model)
    except ValueError:
        allowed = ", ".join(p.value for p in Provider)
        raise ValueError(f"unknown provider '{provider}' (allowed: {allowed})") from None


def resolve_tiers(settings: Settings) -> dict[Tier, TierConfig]:
    """Validate the LLM configuration and return it per tier.

    All problems are collected and reported together, so a misconfigured `.env` can be fixed
    in one go. Messages name settings and env variables, never secret values.
    """
    problems: list[str] = []
    tiers: dict[Tier, TierConfig] = {}

    for tier in TIERS:
        env_name = f"LLM_{tier.upper()}"
        raw: str | None = getattr(settings, f"llm_{tier}")
        if raw is None:
            problems.append(f"{env_name} is not set (expected provider:model, e.g. openai:<model>)")
        primary = _parse_setting(raw, env_name, problems)
        fallback = _parse_setting(
            getattr(settings, f"llm_{tier}_fallback"), f"{env_name}_FALLBACK", problems
        )
        for spec, name in ((primary, env_name), (fallback, f"{env_name}_FALLBACK")):
            if spec is not None and _api_key(settings, spec.provider) is None:
                key_env = _PROVIDER_KEYS[spec.provider][1]
                problems.append(f"{key_env} is required by {name}={spec}")
        if primary is not None:
            tiers[tier] = TierConfig(primary=primary, fallback=fallback)

    if problems:
        raise ConfigurationError(
            "Invalid LLM configuration:\n" + "\n".join(f"  - {p}" for p in problems)
        )
    return tiers


def _parse_setting(value: str | None, env_name: str, problems: list[str]) -> ModelSpec | None:
    if value is None:
        return None
    try:
        return parse_model_spec(value)
    except ValueError as exc:
        problems.append(f"{env_name}: {exc}")
        return None


def _api_key(settings: Settings, provider: Provider) -> SecretStr | None:
    key: SecretStr | None = getattr(settings, _PROVIDER_KEYS[provider][0])
    return key


def init_model(spec: ModelSpec, options: ModelOptions) -> BaseChatModel:
    """Default factory: build a provider chat model through LangChain's `init_chat_model`."""
    kwargs: dict[str, Any] = {
        "api_key": options.api_key,
        "timeout": options.timeout_seconds,
        "max_retries": options.max_retries,
    }
    if options.reasoning:
        if spec.provider is Provider.OPENAI:
            # Reasoning summaries are returned (Responses API) and become visible in LangSmith.
            kwargs["reasoning"] = {"effort": REASONING_EFFORT, "summary": "auto"}
        else:
            kwargs["reasoning_effort"] = REASONING_EFFORT
    model = init_chat_model(spec.model, model_provider=spec.provider.value, **kwargs)
    # A concrete model is returned because a model name is given (no runtime-configurable model).
    assert isinstance(model, BaseChatModel)
    return model


class ModelRegistry:
    """Builds and caches the chat models of each tier. Construction validates the configuration
    but makes no network calls; models are created on first use."""

    def __init__(self, settings: Settings, factory: ModelFactory = init_model) -> None:
        self._settings = settings
        self._factory = factory
        self._tiers = resolve_tiers(settings)
        self._cache: dict[tuple[ModelSpec, bool], BaseChatModel] = {}

    def tier_config(self, tier: Tier) -> TierConfig:
        return self._tiers[tier]

    def chat_model(self, spec: ModelSpec, tier: Tier) -> BaseChatModel:
        reasoning = tier == "heavy" and self._settings.llm_heavy_reasoning
        key = (spec, reasoning)
        if key not in self._cache:
            api_key = _api_key(self._settings, spec.provider)
            assert api_key is not None  # guaranteed by resolve_tiers()
            self._cache[key] = self._factory(
                spec,
                ModelOptions(
                    api_key=api_key.get_secret_value(),
                    timeout_seconds=self._settings.llm_timeout_seconds,
                    max_retries=self._settings.llm_max_retries,
                    reasoning=reasoning,
                ),
            )
        return self._cache[key]

    def structured(
        self, tier: Tier, schema: type[BaseModel]
    ) -> Runnable[LanguageModelInput, dict[str, Any]]:
        """Structured-output runnable for a tier, falling back to the tier's fallback model on
        provider errors. Output: {"raw": AIMessage, "parsed": schema | None, "parsing_error": ...}.
        """
        config = self._tiers[tier]
        primary = self._with_schema(self.chat_model(config.primary, tier), schema)
        if config.fallback is None:
            return primary
        fallback = self._with_schema(self.chat_model(config.fallback, tier), schema)
        return primary.with_fallbacks([fallback])

    @staticmethod
    def _with_schema(
        model: BaseChatModel, schema: type[BaseModel]
    ) -> Runnable[LanguageModelInput, dict[str, Any]]:
        # include_raw: invalid output comes back as `parsing_error` instead of an exception, so
        # it can be told apart from provider errors (which trigger the fallback model).
        runnable: Runnable[LanguageModelInput, dict[str, Any]] = model.with_structured_output(
            schema, include_raw=True
        )  # type: ignore[assignment]
        return runnable
