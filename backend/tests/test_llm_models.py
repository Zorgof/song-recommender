from pathlib import Path

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.errors import ConfigurationError
from app.llm.models import (
    ModelOptions,
    ModelRegistry,
    ModelSpec,
    Provider,
    init_model,
    parse_model_spec,
    resolve_tiers,
)
from app.main import create_app
from tests.conftest import make_app_settings, make_settings
from tests.fake_llm import ScriptedChatModel

# --- parse_model_spec -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("openai:gpt-test", ModelSpec(Provider.OPENAI, "gpt-test")),
        ("anthropic:claude-test", ModelSpec(Provider.ANTHROPIC, "claude-test")),
        ("google_genai:gemini-test", ModelSpec(Provider.GOOGLE_GENAI, "gemini-test")),
        # Fine-tuned OpenAI ids contain colons; only the first one separates the provider.
        ("openai:ft:gpt-test:org:id", ModelSpec(Provider.OPENAI, "ft:gpt-test:org:id")),
        ("  openai:gpt-test  ", ModelSpec(Provider.OPENAI, "gpt-test")),
    ],
)
def test_parse_model_spec(value: str, expected: ModelSpec) -> None:
    assert parse_model_spec(value) == expected


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("gpt-test", "not in the form provider:model"),
        ("openai:", "not in the form provider:model"),
        (":gpt-test", "not in the form provider:model"),
        ("mistral:large", "unknown provider 'mistral' (allowed: openai, anthropic, google_genai)"),
    ],
)
def test_parse_model_spec_rejects(value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        parse_model_spec(value)


def test_model_spec_str_round_trips() -> None:
    assert str(parse_model_spec("openai:gpt-test")) == "openai:gpt-test"


# --- resolve_tiers (startup validation) ---------------------------------------------------------


def test_resolve_tiers_with_fallbacks(tmp_path: Path) -> None:
    settings = make_app_settings(
        tmp_path,
        llm_heavy_fallback="anthropic:claude-test",
        anthropic_api_key="test-anthropic-key",
    )

    tiers = resolve_tiers(settings)

    assert tiers["light"].primary == ModelSpec(Provider.OPENAI, "test-light-model")
    assert tiers["light"].fallback is None
    assert tiers["heavy"].fallback == ModelSpec(Provider.ANTHROPIC, "claude-test")


def test_resolve_tiers_reports_all_problems_at_once(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        llm_heavy="mistral:large",
        llm_light_fallback="anthropic:claude-test",
        openai_api_key="test-openai-key-not-in-message",
    )

    with pytest.raises(ConfigurationError) as excinfo:
        resolve_tiers(settings)

    message = str(excinfo.value)
    assert message.startswith("Invalid LLM configuration:")
    assert "LLM_LIGHT is not set" in message
    assert "LLM_HEAVY: unknown provider 'mistral'" in message
    assert "ANTHROPIC_API_KEY is required by LLM_LIGHT_FALLBACK=anthropic:claude-test" in message
    assert "test-openai-key-not-in-message" not in message


def test_resolve_tiers_requires_key_of_each_used_provider(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path, llm_light="openai:a", llm_heavy="google_genai:b", openai_api_key="test-key"
    )

    with pytest.raises(ConfigurationError, match="GOOGLE_API_KEY is required by LLM_HEAVY"):
        resolve_tiers(settings)


def test_app_does_not_start_with_invalid_llm_configuration(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="LLM_LIGHT is not set"):
        create_app(make_settings(tmp_path))


# --- ModelRegistry ------------------------------------------------------------------------------


class RecordingFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[ModelSpec, ModelOptions]] = []

    def __call__(self, spec: ModelSpec, options: ModelOptions) -> BaseChatModel:
        self.calls.append((spec, options))
        return ScriptedChatModel(model_name=spec.model, script=[{}])


def test_registry_passes_settings_to_the_factory(tmp_path: Path) -> None:
    factory = RecordingFactory()
    settings = make_app_settings(tmp_path, llm_timeout_seconds=12.5, llm_max_retries=4)
    registry = ModelRegistry(settings, factory)

    registry.chat_model(registry.tier_config("light").primary, "light")

    spec, options = factory.calls[0]
    assert spec == ModelSpec(Provider.OPENAI, "test-light-model")
    assert options == ModelOptions(
        api_key="test-openai-key", timeout_seconds=12.5, max_retries=4, reasoning=False
    )


def test_registry_creates_no_models_until_used(tmp_path: Path) -> None:
    factory = RecordingFactory()
    ModelRegistry(make_app_settings(tmp_path), factory)

    assert factory.calls == []


def test_registry_caches_models(tmp_path: Path) -> None:
    factory = RecordingFactory()
    registry = ModelRegistry(make_app_settings(tmp_path), factory)
    spec = registry.tier_config("light").primary

    first = registry.chat_model(spec, "light")
    second = registry.chat_model(spec, "light")

    assert first is second
    assert len(factory.calls) == 1


def test_reasoning_applies_to_heavy_tier_only(tmp_path: Path) -> None:
    factory = RecordingFactory()
    # The same model on both tiers: the heavy one must still get its own, reasoning-enabled copy.
    settings = make_app_settings(
        tmp_path, llm_light="openai:same", llm_heavy="openai:same", llm_heavy_reasoning=True
    )
    registry = ModelRegistry(settings, factory)
    spec = ModelSpec(Provider.OPENAI, "same")

    light = registry.chat_model(spec, "light")
    heavy = registry.chat_model(spec, "heavy")

    assert light is not heavy
    assert [options.reasoning for _, options in factory.calls] == [False, True]


# --- init_model (real provider classes, no network calls) ---------------------------------------


def _options(reasoning: bool = False) -> ModelOptions:
    return ModelOptions(
        api_key="test-provider-key", timeout_seconds=30, max_retries=1, reasoning=reasoning
    )


def test_init_model_openai() -> None:
    model = init_model(ModelSpec(Provider.OPENAI, "gpt-test"), _options())

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-test"
    assert isinstance(model.openai_api_key, SecretStr)
    assert model.openai_api_key.get_secret_value() == "test-provider-key"
    assert model.request_timeout == 30
    assert model.max_retries == 1
    assert model.reasoning is None


def test_init_model_openai_reasoning() -> None:
    model = init_model(ModelSpec(Provider.OPENAI, "gpt-test"), _options(reasoning=True))

    assert isinstance(model, ChatOpenAI)
    assert model.reasoning == {"effort": "medium", "summary": "auto"}


def test_init_model_anthropic() -> None:
    model = init_model(ModelSpec(Provider.ANTHROPIC, "claude-test"), _options(reasoning=True))

    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-test"
    assert isinstance(model.anthropic_api_key, SecretStr)
    assert model.anthropic_api_key.get_secret_value() == "test-provider-key"
    assert model.reasoning_effort == "medium"


def test_init_model_google() -> None:
    model = init_model(ModelSpec(Provider.GOOGLE_GENAI, "gemini-test"), _options())

    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model.endswith("gemini-test")
    assert model.google_api_key is not None
    assert model.google_api_key.get_secret_value() == "test-provider-key"
