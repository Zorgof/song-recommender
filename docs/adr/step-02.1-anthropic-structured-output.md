# ADR-02.1: Step 2 — Native structured output for Anthropic models

- Status: Accepted
- Date: 2026-10-11
- Step: 2 (additional ADR #1)
- Amends: [ADR-02](step-02-llm-layer-and-routing.md) (how `ModelRegistry.structured` asks a
  model for structured output)

## Context

While writing the provider-switching examples for the step 11 documentation, the Anthropic
configuration was built offline with current model ids (`claude-haiku-5-5`,
`claude-sonnet-5-5`, `claude-opus-5-5`). `ModelRegistry.structured()` calls
`with_structured_output(schema, include_raw=True)`, which in `langchain-anthropic` 1.7.5
defaults to `method="function_calling"`: a tool call forced with `tool_choice`. For
`claude-sonnet-5-5` and `claude-opus-5-5` (and any model with thinking on) LangChain warned:

> You are attempting to use structured output via forced tool calling, which is not supported
> when `thinking` is enabled or on claude-sonnet-5-5. This method will raise an
> OutputParserException if tool calls are not generated.

The library's `_supports_forced_tool_choice()` excludes `claude-fable-5-1`,
`claude-opus-5-5` and `claude-sonnet-5-5`. On those models the tool call would be optional. A
reply without it would fail parsing; the light tier would then escalate to heavy, and the heavy
tier would fail with `llm_invalid_output`. FR-20 (switching providers by configuration only)
would not hold for the most likely heavy-tier Claude models.

## Decision / What was implemented

- `ModelRegistry._with_schema()` now receives the model's `ModelSpec`. For
  `Provider.ANTHROPIC` it passes **`method="json_schema"`**: Claude's dedicated structured
  output (`output_config.format`). OpenAI and Gemini keep LangChain's default.
- `langchain-anthropic` converts the Pydantic schema with `anthropic.transform_schema`. That
  function moves constraints the API does not enforce (e.g. `ge`/`le` on the 0–1 scores) into
  the field description, e.g. `{maximum: 1, minimum: 0}`. Checked offline for all four
  schemas (`RouterClassification`, `NeedProfile`, `CuratorOutput`, the eval's `FitVerdict`):
  they convert without errors, with `additionalProperties: false`.
- Pydantic still validates the parsed result, so an out-of-range value is still an invalid
  output, handled as before (escalation).
- Tests (`tests/test_llm_models.py`):
  - for Haiku, Sonnet and Opus 5.5, with reasoning on, both tiers bind `output_config` with
    `json_schema`, bind no `tool_choice`, and LangChain issues no "forced tool calling"
    warning;
  - OpenAI keeps its `response_format`.

  A mutation check (the change reverted) fails the three Anthropic tests.

## Deviations from the plan

None: this restores the plan's intent (FR-20) for current Claude models.

## Issues encountered and how they were solved

- **No Anthropic key is available, so the change is verified offline only:** request
  construction, schema conversion, the absence of the warning. A live smoke test (one
  recommendation with `LLM_LIGHT=anthropic:claude-haiku-5-5` and
  `LLM_HEAVY=anthropic:claude-sonnet-5-5`) is still needed when a key exists.
- **Gemini** builds without warnings with the default method; it is also verified offline only
  (ADR-02).

## Consequences

- The documented Anthropic examples (`claude-haiku-5-5` / `claude-sonnet-5-5`) use a supported
  structured-output path, with or without `LLM_HEAVY_REASONING`.
- If a future `langchain-anthropic` changes the default, this explicit choice keeps the
  behaviour stable.

## Verification

| Command / check | Result |
|-----------------|--------|
| `uv run pytest -q` | 327 passed (4 new) |
| `uv run ruff check .`, `ruff format --check .`, `uv run mypy` | clean |
| Offline build of Anthropic, Gemini and mixed tier configurations | all build; no structured-output warning for Anthropic |
