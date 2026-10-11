# Song Recommender — backend

FastAPI service hosting the LangGraph agents. See the [root README](../README.md) and
[docs/implementation-plan.md](../docs/implementation-plan.md).

## Development

Requires [uv](https://docs.astral.sh/uv/). Python 3.14.8 (pinned in `.python-version`) is installed automatically by uv.

```bash
uv sync                    # create .venv and install dependencies
uv run uvicorn app.main:create_app --factory --reload   # http://localhost:8000/api/docs
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy                # type check (strict, with the pydantic plugin)
```

Configuration is read from environment variables and from the repository-level `../.env`
(see [`.env.example`](../.env.example)). Environment variables take precedence over `.env`.

## Layout

```
app/
  main.py            application factory (create_app), lifespan, request logging middleware
  config.py          Settings (pydantic-settings)
  errors.py          AppError hierarchy and handlers producing {"error": {"code", "message"}}
  logging_config.py  JSON (production) / console (development) logging with secret redaction
  api/               routers, dependencies and response schemas
  llm/               model registry (tiers), structured calls with escalation, routing heuristics
  music/             Spotify and YouTube clients, fuzzy matching, track link cache
  stt/               speech-to-text: STTProvider interface, OpenAI implementation, factory
  agents/            LangGraph graph, nodes, schemas, versioned prompts, RecommendationRunner
  observability/     LangSmith client, root runs, trace URLs
  db/                SQLAlchemy models, async engine, Alembic migrations
evals/               LangSmith evaluation: dataset, target, evaluators, judge prompt, CLI
tests/
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | `{"status": "ok", "database": "ok"}`, or HTTP 503 when the database is unreachable |
| `GET /api/meta` | Public configuration for the frontend (models per tier, STT/LangSmith/catalog flags, locales); never contains secrets |
| `POST /api/transcriptions` | multipart field `audio` (webm/ogg/mp4/wav, ≤ 10 MB) → `{text, language, duration_s}`; `503 stt_unavailable` when STT is disabled |
| `POST /api/recommendations` | `{text, input_mode, locale, transcript?}` → `{status: "completed", recommendation}` or `{status: "needs_clarification", request_id, question}`. `transcript` (voice only) is the raw transcript before the user's edits; it goes to the trace |
| `POST /api/recommendations/{id}/clarification` | `{answer}` → resumes the paused run; `404` unknown id, `409 conflict` if not waiting for an answer |
| `GET /api/recommendations?limit=20&offset=0` | Completed recommendations, newest first, with their feedback and trace link: `{items, total, limit, offset}` |
| `POST /api/recommendations/{id}/feedback` | `{score: "up" \| "down", comment?}` → `204`; one rating per recommendation (rating again replaces it); also sent to LangSmith |
| `GET /api/docs` | Swagger UI; the OpenAPI schema is at `/api/openapi.json` |

Every response carries an `X-Request-ID` header, generated or propagated from the request.
Errors have the shape `{"error": {"code", "message"}}`; codes: `validation_error` (422),
`not_found` (404), `conflict` (409), `llm_unavailable` (503), `llm_invalid_output` (502),
`catalog_unavailable` (503), `stt_unavailable` (503), `audio_too_large` (413),
`unsupported_audio_format` (415), `invalid_audio` (422), `internal_error` (500).
Text limits (FR-6, counted after trimming): description 3–2000 characters, answer 1–2000,
feedback comment up to 1000.

## LLM layer (`app/llm/`)

- **Tiers.** `LLM_LIGHT` and `LLM_HEAVY` are `provider:model` strings (`openai`, `anthropic`,
  `google_genai`), each with an optional `*_FALLBACK`. Both are required: `create_app()` validates
  them and the provider keys, and refuses to start with a message listing every problem.
- **Keys are passed explicitly** from `Settings` to each model (`api_key=`); nothing is read from
  `os.environ`, so values that only live in `.env` work.
- **Structured output** uses the provider's native JSON-schema mode for OpenAI and Anthropic
  (Claude's `output_config`; forced tool calls are unavailable on Sonnet/Opus 5.5, ADR-02.1) and
  LangChain's default for Gemini. Results are always validated with Pydantic.
- **`structured_call(registry, tier, Schema, messages)`** returns a validated `Schema` instance plus
  the tier and model actually used:
  - provider error (after the SDK's retries) → the tier's fallback model, else `LLMUnavailableError` (503);
  - output not matching the schema on `light` → retried once on `heavy` (recorded as an escalation);
    on `heavy` → `LLMInvalidOutputError` (502).
  - The tier and escalation are added to the run metadata and tags, so they appear in LangSmith.
- **Routing heuristics** (`routing.assess_complexity`) classify a description as `simple`,
  `complex` or `uncertain` from its length and contrast markers (EN/PL). `TIER_POLICY` maps
  complexity to the tiers of both agents; `uncertain` cases go to a light-model classifier (step 4).

## Music catalogs (`app/music/`)

- **`MusicCatalog`** (`app.state.catalog`) is what the agent graph uses; it reads the
  `track_link_cache` table first and calls the APIs only on a miss. Found results are cached for
  30 days, "not found" for 1 day; errors are never cached.
  - `lookup_spotify(title, artist)` verifies a curator candidate: the matching track, or `None`
    plus the closest track. An unreachable or unconfigured Spotify raises
    `CatalogUnavailableError` (503, `catalog_unavailable`).
  - `youtube_link(title, artist)` always returns a URL: the video, or a YouTube search URL marked
    unverified (quota used up, API error, not configured, nothing found).
- **`SpotifyClient`**: Client Credentials token, cached and refreshed 60 s before it expires or
  when Spotify rejects it (HTTP 401, one retry). Search in `SPOTIFY_MARKET`, at most 10 results
  (Development Mode limit): first with `track:`/`artist:` filters, then as free text.
- **`YouTubeClient`**: `search.list` with `type=video`, `videoCategoryId=10` (Music). The API key
  is sent in the `X-Goog-Api-Key` header, never in the URL. After a `quotaExceeded` error no call
  is made until the quota resets (midnight Pacific time).
- **Matching** (`matching.py`): titles and artists are normalized (case, accents incl. `ł`,
  punctuation, "Remastered"/"Live"/"feat." markers, a leading "The") and compared with rapidfuzz;
  both the title and the artist must score at least 85. `normalized_key(artist, title)` is the
  cache key (`"artist|title"`).

## Speech-to-text (`app/stt/`)

- **`STTProvider`** (`app.state.stt`): `transcribe(audio, mime) -> Transcript(text, language,
  duration_s)`. It is `None` when STT is disabled (`STT_PROVIDER=none`, or no `OPENAI_API_KEY`);
  `/api/meta` then reports `stt.enabled=false` and the endpoint answers `503 stt_unavailable`.
- **`OpenAISTT`** calls `/v1/audio/transcriptions` with `STT_MODEL` (default `gpt-transcribe`),
  `OPENAI_API_KEY`, `LLM_TIMEOUT_SECONDS` and `LLM_MAX_RETRIES`. No language hint is sent: the
  language is detected. `language` is filled by models that report it (`gpt-transcribe`),
  `duration_s` by models billed per audio minute; otherwise they are `null`.
- Audio OpenAI cannot decode (corrupted, too short) → `422 invalid_audio`; any other provider
  error (key, model id, rate limit, outage) → `503 stt_unavailable`, logged without the message.
- The audio is not stored, logged or traced; the transcript is not logged either (NFR-5).

Manual check with a real key (run the backend first):

```bash
curl -s -F "audio=@sample-pl.webm;type=audio/webm" http://localhost:8000/api/transcriptions
# {"text":"Miałem dziś ciężki dzień…","language":"pl","duration_s":6.1}
```

## Agent graph (`app/agents/`)

`app.state.recommender` (`RecommendationRunner`) runs one request:
`start(text, input_mode=…, locale=…)` returns `Completed(recommendation)` or
`NeedsClarification(request_id, question)`; `answer(request_id, answer)` resumes a paused run.

```
route_request → need_analyst → [ask_clarification → need_analyst]
             → music_curator → verify_candidates → [music_curator, up to 3 attempts] → finalize
```

- **Routing:** heuristics, then a light-model classifier only for uncertain cases.
- **Clarification:** at most one question, via LangGraph `interrupt()`. The paused state lives in
  `DATA_DIR/checkpoints.db`, so it survives a restart.
- **Escalation:** invalid structured output → heavy (ADR-02); no verified candidate → the next
  curator attempt runs on heavy, with the rejected candidates as feedback.
- **Verification:** concurrent Spotify lookups. Songs from the last `HISTORY_EXCLUDE_LAST_N`
  recommendations are excluded. Without a verified song, unverified search links are returned.
- **Prompts:** `app/agents/prompts/<name>.v<N>.md`, with a `<!-- system -->` and a
  `<!-- user -->` section and `{{placeholders}}`. The highest version is used and recorded on
  every trace. To change a prompt, add a new version file.
- **LangSmith:** with `LANGSMITH_TRACING=true` and a key, every run is a root run
  `recommend_song` (`run_id` = request id; the resumed run gets a derived id in the same
  thread). It carries the verbatim input, models, prompt versions, routing, escalations and
  tags, and LLM, node and catalog runs nest under it.

## Evaluations (`evals/`)

An experiment runs the real agent graph (real models, real Spotify) on every example of
`evals/dataset.jsonl` and scores the results in LangSmith. It needs the same `.env` as the
app, with LangSmith enabled.

```bash
uv run python -m evals.run_evals --limit 3            # smoke run, ~30 s
uv run python -m evals.run_evals                      # all 32 examples, ~3-4 min
uv run python -m evals.run_evals --repetitions 3 --description "curator v2: ..."
uv run python -m evals.run_evals --sync-only          # only update the LangSmith dataset
```

- **Dataset.** `dataset.jsonl` is the source of truth. Every run syncs it to the LangSmith
  dataset `song-recommender-evals`: new lines are created, changed ones updated, removed ones
  deleted (example ids are derived from the line's `id`).
- **Target** (`target.py`). One example = one graph run, with no exclusion history. A
  clarifying question is answered with the example's `clarification_answer`, or a generic
  answer. App errors count as failed examples. A separate database (`evals/.data/`, git-ignored)
  is used and is also the catalog cache. YouTube is off unless `--with-youtube` (daily quota).
- **Metrics** (`evaluators.py`):
  - per example: `completed`, `spotify_verified`, `latency_s`, `within_15s` (NFR-3),
    `escalated`, `curation_attempts`, `clarified`, `explanation_language` (FR-15);
  - LLM-as-judge `fit` (0-1) with aspects `fit_energy`, `fit_goal`, `fit_requests`,
    `fit_specificity` and `profile_faithful`; prompt `evals/prompts/fit_judge.v<N>.md`;
    model: `LLM_HEAVY`, or `--judge-model provider:model`;
  - over the experiment: `distinct_songs`, `distinct_artists`.
- **Comparing versions.** Experiments are named after the prompt versions
  (`curator-v1.need_analyst-v1.router-v1-<id>`); their metadata records the prompt versions,
  models, judge model and prompt, candidate count, app version, dataset version and git
  commit. Compare them in LangSmith: Datasets → `song-recommender-evals` → Experiments. Results
  vary between runs, so compare with `--repetitions 2` or more.

## Database and migrations

SQLite files live in `DATA_DIR` (default `./data`, relative to the working directory).
Migrations run automatically on application startup (`alembic upgrade head`).

Creating a new migration after changing `app/db/models.py`:

```bash
uv run alembic revision --autogenerate --rev-id 0002 -m "short description"
# review the generated file in app/db/migrations/versions/, then:
uv run alembic upgrade head
uv run alembic check        # must report "No new upgrade operations detected."
```

Things to check in every generated revision:

- **Enum columns:** autogenerate renders each enum CHECK constraint twice (named after the enum
  and named by the convention). Keep only the `op.f("ck_<table>_<enum name>")` one and set
  `create_constraint=False` on the `sa.Enum(...)` in the migration (see `0001_initial_schema.py`).
- **Application types** such as `UTCDateTime` are rendered as plain SQLAlchemy types by
  `render_item` in `env.py`; revision scripts must never import `app` code.
- SQLite cannot `ALTER` most things; migrations use batch mode (`render_as_batch=True`).
