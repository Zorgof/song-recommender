# ADR-02: Step 2 — LLM layer and routing primitives

- Status: Accepted
- Date: 2026-10-07
- Step: 2

## Context

Step 2 of the [implementation plan](../implementation-plan.md) builds the provider-agnostic LLM
layer that both agents (step 4) will use:
- a model registry for the light and heavy tiers;
- a structured-output helper that validates answers and escalates from light to heavy;
- the routing heuristics.

"Done when":
- unit tests with fake chat models cover tier selection, fallback and escalation;
- a missing key gives a clear startup error;
- one smoke call works with the real OpenAI key.

## Decision / What was implemented

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| langchain | 1.4.3 | `init_chat_model` (brings langgraph 1.2.14, needed in step 4) |
| langchain-core | 1.6.7 | Runnables, messages, structured output, callbacks |
| langchain-openai | 1.6.7 | OpenAI (default provider; openai SDK 3.26.0) |
| langchain-anthropic | 1.7.5 | Anthropic (anthropic SDK 1.11.0) |
| langchain-google-genai | 4.4.0 | Gemini (google-genai 2.28.0) |
| langsmith | 0.14.4 | Installed as a dependency; wired up in step 4 |

All three provider integrations are installed, so switching providers really is a change to
`.env` only (FR-20).

### Default models (OpenAI, verified against the account's model list)

| Tier | Model | Why |
|------|-------|-----|
| light | `openai:gpt-6-luna` | GPT-6 family, low-cost and fast ($0.10 / $0.50 per 1M tokens) |
| heavy | `openai:gpt-6.1-sol` | Newest mid-tier model ($2 / $10 per 1M); `gpt-6-astra` is 5× more expensive and not needed for this task |

The ids were taken from `GET /v1/models` on the developer's key (both are available) and checked
against published pricing. They are set in `.env.example`; code contains no model ids.

### Model registry — `app/llm/models.py`

- `parse_model_spec("provider:model")` → `ModelSpec`. Providers: `openai`, `anthropic`, `google_genai` (LangChain's names). Only the first `:` separates the provider, so fine-tuned ids such as `openai:ft:…:…` work.
- `resolve_tiers(settings)` validates `LLM_LIGHT`, `LLM_HEAVY` (both required), `LLM_*_FALLBACK` (optional) and the API key of every provider they use.
  - **All problems are reported in one `ConfigurationError`.**
  - Messages name variables, never values.
- `create_app()` builds the `ModelRegistry`, which runs this validation, so **the app refuses to start** with a misconfigured `.env` (FR-25). The registry is available as `app.state.models`.
- `ModelRegistry`:
  - creates models lazily (no network calls at startup) and caches them per (spec, reasoning flag);
  - its factory is injectable (tests use it).
- `init_model()` (the default factory) calls `init_chat_model` with **explicit** `api_key`, `timeout` and `max_retries`. All three provider classes accept these names, so there is no per-provider branching. This follows up the ADR-01 consequence: the SDKs do not see values that live only in `.env`.
- `LLM_HEAVY_REASONING=on` (heavy tier only):
  - OpenAI: `reasoning={"effort": "medium", "summary": "auto"}`, i.e. the Responses API with reasoning summaries, which will be visible in LangSmith;
  - Anthropic and Gemini: `reasoning_effort="medium"`.
- `ModelRegistry.structured(tier, schema)` returns `with_structured_output(schema, include_raw=True)`, wrapped in `with_fallbacks([fallback])` when a fallback is configured.
  - `include_raw` turns invalid output into a `parsing_error` value instead of an exception.
  - Only provider errors therefore trigger the fallback model; invalid answers are handled by escalation.
- New settings: `LLM_TIMEOUT_SECONDS` (default 60) and `LLM_MAX_RETRIES` (default 2).

### Structured calls — `app/llm/structured.py`

`structured_call(registry, tier, Schema, messages, config=…)` returns
`StructuredResult(value, tier_requested, tier_used, model, escalated, escalation_reason)`.

| Situation | Behaviour |
|-----------|-----------|
| Valid output | Returned; `model` is the name reported by the provider |
| Invalid output on light | Retried once on heavy; `escalated=True`, reason `invalid_structured_output` |
| Invalid output on heavy | `LLMInvalidOutputError` (new error code `llm_invalid_output`, HTTP 502) |
| Provider error | The tier's fallback model, if configured; otherwise `LLMUnavailableError` (503). **No escalation to heavy** |

Each attempt adds metadata `tier`, `escalated`, `escalation_reason` and the tag `tier:<tier>` to the
run config, on top of the caller's config. LangSmith (step 4) therefore shows on every LLM run
which tier answered and why.

### Routing heuristics — `app/llm/routing.py`

`assess_complexity(text, input_mode)` is a pure function returning `simple`, `complex` or
`uncertain`, with reasons, word count and the contrast markers found:

| Rule (applied in this order) | Verdict |
|------------------------------|---------|
| fewer than 5 words | uncertain (too little to judge; the classifier or a clarifying question decides) |
| 150 words or more | complex |
| 2 or more contrast markers | complex (mixed or conflicting feelings) |
| at most 60 words (90 for voice) and no markers | simple |
| anything else (one marker, or medium length) | uncertain |

- Contrast markers are bilingual EN/PL ("but", "although", "z jednej strony", "nie wiem", …).
- They are matched as whole words, so "but" does not match "button".
- Typographic apostrophes (`’`) are normalised first.
- `TIER_POLICY` maps complexity to the tiers of (need analyst, curator): simple → (light, light), complex → (heavy, heavy).
- `decide()` builds the `RoutingDecision` that step 4 records in state and trace metadata.

### Tests (96 in total, 52 new)

- `tests/fake_llm.py`: `ScriptedChatModel`, a `BaseChatModel` that supports `bind_tools` and answers with scripted tool calls or exceptions. The tests therefore go through **LangChain's real** `with_structured_output`, output parser and `with_fallbacks`.
- `test_llm_models.py`:
  - spec parsing, valid and invalid;
  - validation: all problems in one message, missing keys per provider, no secrets in messages, `create_app` refuses to start;
  - the registry passes keys, timeout, retries and the reasoning flag (heavy only), creates models lazily and caches them;
  - `init_model` builds the real `ChatOpenAI` / `ChatAnthropic` / `ChatGoogleGenerativeAI` classes with the right key and options, offline.
- `test_structured_call.py`:
  - light success, heavy on request;
  - escalation on invalid or incomplete output; error after a failed escalation; no retry on heavy;
  - fallback on a provider error; unavailable without a fallback (and no escalation); primary and fallback both failing;
  - tier and escalation metadata and tags reach callbacks.
- `test_routing.py`: EN/PL simple, uncertain and complex cases; whole-word matching; the voice threshold; apostrophes; the tier policy.
- `tests/conftest.py`: new `make_app_settings()` adds the minimal LLM configuration the app needs to start. `make_settings()` stays free of defaults, so the configuration tests still see the real ones.

## Deviations from the plan

| Plan | Actual | Reason |
|------|--------|--------|
| Error codes `llm_unavailable`, … | Added `llm_invalid_output` (502) | "The model answered, but with garbage" is different from "the provider is down" (503) and should be visible as such. |
| `get_model(tier)` with `with_fallbacks` | `ModelRegistry.structured(tier, schema)` composes structured output and fallbacks | `RunnableWithFallbacks` has no `with_structured_output`, so the schema has to be applied to each model *before* the fallback is composed. |
| Escalation "on failure" | Escalation only for invalid output; provider errors use the fallback model | A provider outage usually affects both tiers of the same provider; the fallback is the configured answer to that. |
| Routing classifier in this step? | Only the heuristics; the LLM classifier for `uncertain` comes with the graph in step 4 | As planned ("Router heuristics, as a pure function"); the classifier needs the prompt files of step 4. |

## Issues encountered and how they were solved

1. **The app no longer started in the existing tests** (14 errors): they built it without an LLM configuration. Solved with `make_app_settings()` and a `settings` fixture that has the minimal valid configuration. The test "meta with nothing configured" became "meta with minimal configuration".
2. **`init_chat_model` is typed as returning `Any`** (mypy `no-any-return`). Added `assert isinstance(model, BaseChatModel)`, which is also correct at runtime because a model name is always given.
3. **The provider key fields are typed as `SecretStr | Callable`** in `ChatOpenAI`/`ChatAnthropic`; the tests narrow them with `isinstance`.
4. **LangChain adds internal tags** (`map:key:raw`) to nested runs. The metadata test checks that our tags are a subset instead of comparing exact lists.
5. **ruff RUF001 on the typographic apostrophe** `’`. It is intentional (phones and transcripts produce it), so it is written as `’` in code and tests.
6. **`google-genai` raises a `DeprecationWarning` on Python 3.14** (`_UnionGenericAlias`, removal planned for 3.17). This is third-party code and not actionable here, so exactly this warning from exactly that module is filtered in the pytest configuration.

## Findings from the live smoke test (input for step 4)

The test used a NeedProfile-like schema (`Literal`, optional field, list, bounded float) and a Polish input:
"Długi dzień w pracy, jestem wykończony, ale jutro wolne. Chcę coś na wyciszenie."

| Run | Result | Latency |
|-----|--------|---------|
| light `gpt-6-luna` | valid, goal `calm` | 3.9 s |
| heavy `gpt-6.1-sol` | valid, goal `calm`, energy 0.2 | 7.0 s |
| heavy + reasoning (Responses API) | valid, goal `calm`, energy 0.2 | 5.8 s |

- OpenAI's default `json_schema` structured output accepts the schema style planned for the agents, including with reasoning on.
- **The light model reported `energy = 1.0` for an exhausted user**, i.e. it read the scale backwards; the heavy model reported 0.2. The step 4 schemas and prompts must define each scale explicitly in the `Field(description=…)`, e.g. "0 = exhausted, 1 = very energetic". Eval cases (step 10) should check scale direction.
- Latency: 4–7 s per call. Router classifier + analyst + curator is 3–4 sequential calls, so the 15 s target (NFR-3) is tight. The heuristics skipping the classifier, and the light tier for simple requests, matter.

## Consequences

- **The developer's `.env` must set `LLM_LIGHT` and `LLM_HEAVY`** (see `.env.example`); otherwise the backend refuses to start. This is verified: without them the server exits with the two "is not set" lines; with them it starts and `/api/meta` lists the models.
- Step 4 uses `structured_call` for every agent call, `assess_complexity` + `decide` in the `route_request` node, and must:
  - add the light-model classifier for `uncertain`;
  - configure LangSmith explicitly (key, workspace id, endpoint, project);
  - describe score scales in the schemas (see findings).
- Switching a tier to Anthropic or Gemini is a `.env` change. It has only been tested offline (model construction); a live smoke test is needed when such a key is available.

## Verification

| Command / check | Result |
|-----------------|--------|
| `uv run pytest -q` | 96 passed, no warnings |
| `uv run ruff check .` / `ruff format --check .` | clean |
| `uv run mypy` (strict) | no issues in 35 source files |
| Live: `structured_call` light / heavy / heavy+reasoning on the real OpenAI key | all valid (see findings) |
| Live: `uvicorn app.main:create_app --factory` with the developer's `.env` (no tiers) | exits with `ConfigurationError: Invalid LLM configuration: LLM_LIGHT is not set …, LLM_HEAVY is not set …` |
| Live: same, with `LLM_LIGHT`/`LLM_HEAVY` set | starts; `/api/meta` shows `openai:gpt-6-luna` / `openai:gpt-6.1-sol` |
