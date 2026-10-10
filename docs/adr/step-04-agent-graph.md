# ADR-04: Step 4 — Agent graph

- Status: Accepted (amended by [ADR-04.1](step-04.1-three-candidates.md))
- Date: 2026-10-10
- Step: 4

## Context

Step 4 of the [implementation plan](../implementation-plan.md) builds the multi-agent
recommendation flow on top of the LLM layer (ADR-02) and the catalog layer (ADR-03):
- state and schemas, with the UI locale in the state;
- versioned prompts that follow the language rules (reasoning in English, user-facing text in
  the UI locale);
- the six graph nodes, the graph with a SQLite checkpointer, and the exclusion list from history;
- LangSmith wiring: run name, run id, verbatim inputs, metadata, tags, thread, prompt versions.

"Done when":
- graph tests with fake LLMs and mocked catalogs cover the happy path (en and pl), the
  clarification path, the retry plus escalation path and the all-unverified fallback;
- one manual run with real keys produces a readable LangSmith trace showing the user prompt,
  the rendered agent prompts, the rationales and the choice.

## Decision / What was implemented

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| langgraph | 1.2.14 | Graph, `interrupt`, runtime context (was installed through `langchain`; now direct) |
| langgraph-checkpoint-sqlite | 3.1.1 | `AsyncSqliteSaver` for `checkpoints.db` (brings `sqlite-vec` 0.1.9) |
| langsmith | 0.14.4 | Root runs, `@traceable`, client (was installed; now direct) |

### Package layout

| Path | Content |
|------|---------|
| `app/agents/schemas.py` | `NeedProfile`, `SongCandidate`, `CuratorOutput`, `RouterClassification`, `Recommendation` |
| `app/agents/state.py` | `GraphState`, `AgentDeps`, the `Catalog` protocol, limits |
| `app/agents/prompt_loader.py` | Versioned prompt files, `PromptLibrary` |
| `app/agents/prompts/*.v1.md` | `router`, `need_analyst`, `curator` |
| `app/agents/nodes/` | One module per node, plus `common.py` |
| `app/agents/graph.py` | `build_graph(checkpointer)` |
| `app/agents/runner.py` | `RecommendationRunner`: `start()`, `answer()` |
| `app/db/repositories.py` | `RecommendationRepository` |
| `app/observability/tracing.py` | `Tracing`, `root_run_id`, `build_client` |

### Graph

```
START → route_request → need_analyst ─┬─→ ask_clarification (interrupt) → need_analyst
                                      └─→ music_curator → verify_candidates ─┬─→ music_curator (retry)
                                                                             └─→ finalize → END
```

| Node | What it does |
|------|--------------|
| `route_request` | `assess_complexity` (ADR-02). `simple`/`complex` are decided without an LLM. `uncertain` goes to the light-model classifier (`RouterClassification`); if its output is invalid even after escalation, the request is routed as `complex`. |
| `need_analyst` | `NeedProfile` on the routed tier. If the model asks for clarification **and** wrote a question **and** no answer exists yet, the graph goes to `ask_clarification`. After the answer it runs again with the question and answer in the prompt and the instruction not to ask again. |
| `ask_clarification` | `interrupt({"question": …})`. Resumed with `Command(resume=answer)`. Runs at most once: once an answer is in the state, `after_need_analyst` always continues to the curator. |
| `music_curator` | `CuratorOutput` (5 candidates asked, 3 since ADR-04.1; 1–10 accepted). Attempt 1 on the routed tier; retries always on heavy, with the rejected candidates and reasons in the prompt. A light→heavy retry is recorded as escalation `no_verified_candidates`. |
| `verify_candidates` | Drops candidates that were recommended recently or are duplicates. Looks up the rest **concurrently** (`asyncio.gather`) with `MusicCatalog.lookup_spotify`. Rejection reasons include the closest Spotify track and its scores. `CatalogUnavailableError` sets `catalog_unavailable`. |
| `finalize` | Highest-ranked verified candidate; otherwise the best candidate of the last attempt that is not excluded, with a Spotify search URL (`spotify_verified=false`). YouTube lookup for the chosen song only. Builds the `Recommendation` and persists the completed row. |

Routing after `verify_candidates`: any verified → `finalize`; Spotify unavailable → `finalize`
(retrying would not help); fewer than 3 attempts → `music_curator`; otherwise `finalize`.

### State and dependencies

- `GraphState` (`TypedDict`) holds only JSON-like values; nodes validate them back into the
  Pydantic schemas.
  - `rejected` and `escalations` accumulate across attempts (`operator.add` reducers).
  - `models_used` (node → model reported by the provider) is merged.
- Dependencies (`AgentDeps`: model registry, catalog, prompts, repository) reach the nodes
  through LangGraph's **runtime context** (`context_schema=AgentDeps`, `ainvoke(…, context=deps)`).
  They are passed on every run, including the resume, and are never checkpointed.
- The catalog is typed as a `Catalog` protocol, which `MusicCatalog` satisfies; tests pass a fake.

### Schemas and prompts

- Every score in `NeedProfile` states its scale and direction in its `Field(description=…)`
  (finding of ADR-02: the light model read `energy` backwards). The descriptions are part of
  the JSON schema the model receives.
- Language rules:
  - `summary`, `emotions`, `day_context`, `musical_hints`, `avoid`, `rationale`, `fit_notes`
    are in English;
  - `summary_localized`, `clarification_question`, `explanation` are in the UI locale;
  - the locale is passed by name ("Polish"/"English") into both agents' prompts.
- Prompt files `app/agents/prompts/<name>.v<N>.md`:
  - a `<!-- system -->` and a `<!-- user -->` section, placeholders `{{name}}`;
  - rendering fails on a missing or unused value;
  - the highest version is loaded unless one is pinned;
  - the user text is wrapped in `<user_description>` tags, and the prompts say it is data,
    not instructions.
- `create_app()` loads the `PromptLibrary`, so a missing or malformed prompt file stops the
  app at startup.

### Runner and persistence

`RecommendationRunner` is what the API (step 5) will call.

- `start(text, input_mode, locale, transcript=None)`:
  1. creates the `recommendations` row as `pending`;
  2. loads the exclusion list: the last `HISTORY_EXCLUDE_LAST_N` completed recommendations;
  3. runs the graph.
- `answer(request_id, answer)`:
  - raises `NotFoundError` for an unknown id, and the new `ConflictError` (`conflict`, HTTP 409)
    if the row is not waiting for an answer;
  - otherwise stores the answer and resumes the graph from `checkpoints.db`.
- Outcomes: `Completed(recommendation)` or `NeedsClarification(request_id, question)`.
- Row status:

  | Event | Written by | Status |
  |-------|-----------|--------|
  | start | runner | `pending` |
  | graph paused | runner | `needs_clarification` (+ question, profile so far) |
  | answer received | runner | `pending` (+ answer) |
  | graph finished | `finalize` | `completed` (+ all result fields, `models_used`, `escalated`) |
  | any error | runner | `failed` (+ the error code, e.g. `llm_unavailable`) |

- The lifespan opens `AsyncSqliteSaver` on `DATA_DIR/checkpoints.db`
  (`Settings.checkpoints_path`), builds the graph and exposes `app.state.recommender`. The
  LangSmith client is flushed on shutdown.

### LangSmith

- `Tracing` builds its own `langsmith.Client` from Settings: key, `LANGSMITH_ENDPOINT` and
  `LANGSMITH_WORKSPACE_ID` (ADR-01.2). Nothing is read from `os.environ`.
- **Root run `recommend_song`:** each graph run is wrapped in `langsmith.trace(...)` inside
  `tracing_context(enabled=…, client=…, project_name=…)`. The graph, the node runs, the LLM
  runs (full rendered messages and raw output) and the `@traceable` catalog calls
  (`spotify_lookup`, `youtube_lookup`, `run_type="tool"`) nest under it automatically.
  - With tracing off, `enabled=False` also switches off tracing a developer may have enabled
    through environment variables.
- **Run ids:** the first run has `run_id = request_id`. The run that resumes after the
  clarifying question has `uuid5(namespace, request_id)` (`root_run_id(…, resumed=True)`).
  Both are known in advance, so feedback in step 5 can target the right run without storing
  extra ids.
- **Inputs:** the verbatim `user_input`, `input_mode`, `locale`, and `transcript` when given.
  The resumed run also has the clarification question and answer (FR-40).
- **Metadata at the start:** `request_id`, `thread_id` (= request id; groups both runs as one
  LangSmith thread, FR-44), `resumed`, `app_version`, `models` and `fallback_models` per tier,
  `prompt_versions`.
- **Metadata at the end:** `routing_complexity`, `routing_source`, `routing_reasons`,
  `models_used`, `escalations`, `curation_attempts`, `status`, `spotify_verified`,
  `youtube_verified`.
- **Tags:** `text`/`voice`, `locale:<xx>`, `clarified`, `escalated`.
- **Outputs:** the recommendation, or the clarifying question.
- **Trace link:** `Recommendation.trace_url` is `<project url>/r/<run id>?poll=true`.
  - The project (tenant and project id) is read once per process.
  - If it cannot be read (e.g. before the first trace has created the project), the link is
    `None` and the next request tries again.
- Each curator LLM run also has the metadata `curation_attempt`.
- From ADR-02, each LLM run already carries `tier`, `escalated`, `escalation_reason`.

### Tests (238 in total, 37 new)

- `tests/fake_llm.py`: new `SchemaRoutedChatModel`. It answers by the bound schema (the tool
  name), with a queue of answers per schema, and records every call with its messages. The
  graph's calls can then be scripted independently of their order.
- `tests/agent_fakes.py`: builders for `NeedProfile` / `CuratorOutput` answers, a `FakeCatalog`
  (known tracks and videos, Spotify outage, recorded lookups) and `make_harness()`, which wires
  the real graph, runner, prompts and SQLite repository.
- `test_agent_graph.py` (16):
  - happy path EN (fields, light tier only, concurrent verification, YouTube only for the pick,
    the persisted row) and PL (Polish texts; the locale reaches both prompts);
  - complex request → heavy only; uncertain request → light classifier → heavy;
  - clarification: pause, row state, resume, the question and answer in the second prompt,
    routing not repeated;
  - asked at most once; `answer()` errors;
  - **resume after a restart** (two `AsyncSqliteSaver` instances on the same file);
  - retry with escalation to heavy and feedback about the rejected candidates;
  - all attempts unverified → search links; Spotify unavailable → no retries;
  - exclusion of recent songs, and the `HISTORY_EXCLUDE_LAST_N=0` case;
  - invalid `NeedProfile` → escalation; LLM failure → row `failed`; the voice note in the prompt.
- `test_tracing.py` (6), with a `RecordingClient` (a `langsmith.Client` whose `create_run` /
  `update_run` / `read_project` record instead of sending):
  - root run id, inputs, outputs, metadata and tags;
  - node, LLM and tool runs all in one trace;
  - the trace URL;
  - the two runs of a clarification sharing one thread, with the link on the resumed run;
  - escalation tags; an unreadable project; stable run ids; client construction.
- `test_prompts.py` (11): the shipped prompts and their placeholders, rendering, version
  choice, malformed and missing files.
- `test_repositories.py` (2): `recent_tracks` (only completed, newest first, limit) and the
  status transitions.
- `test_music_catalog.py` (+1): the app exposes `app.state.recommender`.

## Deviations from the plan

| Plan | Actual | Reason |
|------|--------|--------|
| Root run named `recommend_song` with `run_id = request_id` via `RunnableConfig` | An explicit `langsmith.trace` root run around the graph; the resumed run has a derived id | Metadata known only at the end (routing, escalations, verification) and the `escalated` tag must go on the root run, which needs a handle to it. Two runs (before and after the question) cannot share one id. |
| Metadata key `routing.complexity` | `routing_complexity` (flat keys) | Flat keys are easier to filter on in LangSmith. |
| `finalize` persists the result | `finalize` writes the completed row; the runner writes `pending`, `needs_clarification` and `failed` | Those states happen outside the graph (before it, at the interrupt, on an exception). |
| Exclusion list "loaded from history" in the graph | Loaded by the runner and passed in the initial state | Keeps the nodes free of history queries; the list is visible in the checkpointed state. |
| State holds the Pydantic models | JSON-like values, validated in the nodes | Checkpoint serialization without registering custom types. |
| Prompts in `agents/prompts/` | Plus the loader `agents/prompt_loader.py` | A module named `prompts.py` next to the `prompts/` directory would be confusing. |
| Error codes of 2.6 | New `conflict` (409) | Answering a recommendation that is not waiting for an answer. |
| Router classifier for `uncertain` | Invalid classifier output → routed as `complex` | Routing must not fail a request; heavy is the safe side. |
| Up to 3 curator attempts | No retries when Spotify is unavailable | A retry cannot be verified either; the user gets unverified links sooner. |

## Issues encountered and how they were solved

1. **LangGraph has no node type taking `(state, config, runtime)`** (mypy `call-overload`).
   Nodes take `(state, runtime)` and read the run config with `langgraph.config.get_config()`,
   which they pass to `structured_call`.
2. **Concurrent catalog lookups complete in any order.** The test compares them as a sorted list.
3. **`langsmith.Client.read_project` loses its return type through a deprecation decorator**,
   which broke mypy's narrowing. Solved with a small typed helper `_read_project()`.
4. **The test's fake `TracerSession`** needed `reference_dataset_id` (a required field). This
   was a test-only mistake; the code under test was correct.
5. **Wrong recording chosen live** ("An Ending (Ascent)" credited to a collaboration). Fixed in
   the step 3 ranking; see [ADR-03.1](step-03.1-prefer-artists-own-recording.md).

## Findings from the live run (real OpenAI, Spotify, YouTube, LangSmith)

Four runs with the developer's keys (data in a temporary directory):

| Case | Route | Result | Total time |
|------|-------|--------|------------|
| EN, simple ("tired after work, calm before sleep") | heuristics → simple → light | Brian Eno - An Ending (Ascent); Spotify + YouTube verified | 21.0 s |
| PL, mixed feelings (promotion vs. moving away) | heuristics → complex → heavy | The Head And The Heart - Rivers and Roads; verified | 36.8 s |
| PL, "hmm" | classifier → simple; question asked | "Jak się teraz czujesz i co chcesz, żeby muzyka dla Ciebie zrobiła?" | 7.1 s |
| PL, the answer | resumed | Tycho - A Walk; verified | 35.7 s |

- **Readable traces.** Each trace is one tree: `recommend_song` → `recommendation_graph` → node
  runs → `ChatOpenAI` runs (model, tier, full rendered prompt, tool-call output with the
  rationales) → `spotify_lookup` ×5 (concurrent, 0.2–0.5 s) → `youtube_lookup` (0.3 s).
  - The root shows the verbatim input, the routing, models used, attempts and prompt versions.
  - The "View trace" links resolve to the runs.
  - The `with_structured_output` internals add a few `RunnableSequence`/`RunnableLambda` rows
    under each LLM node; they are noise but harmless.
- **Language rules hold:** the Polish requests got Polish `need_summary` and `explanation`,
  the English one English; the profiles and rationales were English.
- **Latency is over the NFR-3 target (15 s).** The curator call dominates:

  | LLM run | Time | Prompt / completion tokens | Of which reasoning |
  |---------|------|---------------------------|--------------------|
  | need_analyst, light | 5.8 s | 1008 / 354 | 82 |
  | curator, light | 13.9 s | 788 / 1300 | 665 |
  | need_analyst, heavy | 6.6 s | 1034 / 290 | 0 |
  | curator, heavy | 29.4 s | 865 / 1197 | 258 |

  - `gpt-6-luna` reasons by default: half of the light curator's output is hidden reasoning.
  - The heavy model writes about 40 tokens/s.
  - Verification and YouTube add under 1 s.

## Consequences

- Step 5:
  - `POST /api/recommendations` calls `app.state.recommender.start(...)`; the clarification
    endpoint calls `answer(...)` and maps `ConflictError` to 409;
  - `POST /feedback` targets `root_run_id(request_id, resumed=<clarification_answer is set>)`;
  - the history can show `Tracing.trace_url(...)` for the same run id;
  - `RecommendationRepository` gets the paging query for `GET /api/recommendations`.
- **Latency needs a decision** (it is not part of the step 4 "done when"). Options, cheapest
  first:
  1. lower the reasoning effort of the light tier (`gpt-6-luna` reasons by default);
  2. shorter candidate fields (one-sentence `rationale`, short `fit_notes`) in `curator.v2`;
  3. fewer candidates per attempt (e.g. 3 instead of 5);
  4. generate the user-facing `explanation` only for the chosen song (one extra light call);
  5. SSE progress (already future work) to make the wait visible.

  Options 2–3 are prompt or constant changes that step 10's evals can measure. Option 1 changes
  the model registry and needs a check of which parameters the model accepts.
- Prompt changes are made by adding `<name>.v2.md`; the version shows up in every trace.

## Verification

| Command / check | Result |
|-----------------|--------|
| `uv run pytest -q` | 238 passed, no warnings |
| `uv run ruff check .` / `ruff format --check .` | clean |
| `uv run mypy` (strict) | no issues in 70 source files |
| Live: 3 requests + 1 clarification answer through `app.state.recommender` with the developer's `.env` | all completed, verified links (see the findings) |
| Live: the four traces read back through the LangSmith API | complete trees as described; metadata and tags present |
