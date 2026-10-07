# ADR-01: Step 1 — Backend foundation

- Status: Accepted — amended by [ADR-01.2](step-01.2-langsmith-workspace-id.md)
- Date: 2026-10-07
- Step: 1

## Context

Step 1 of the [implementation plan](../implementation-plan.md) builds the backend base that
every later step relies on:
- configuration;
- the application factory;
- logging that never leaks API keys;
- one error format for all endpoints;
- the health and meta endpoints;
- the SQLite database with migrations applied on startup.

"Done when": API tests for health and meta pass, and the DB file is created on startup.

## Decision / What was implemented

### Dependencies (`backend/pyproject.toml`, locked in `uv.lock`)

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | 0.142.2 | Web framework (on Starlette 1.7.0) |
| uvicorn[standard] | 0.54.0 | ASGI server (uvloop, httptools) |
| pydantic / pydantic-settings | 2.13.5 / 2.15.0 | Schemas and settings |
| sqlalchemy[asyncio] | 2.1.3 | ORM, async engine |
| aiosqlite | 0.22.1 | Async SQLite driver used at runtime |
| alembic | 1.20.0 | Migrations |
| httpx2 (dev) | 2.13.1 | HTTP client used by FastAPI's `TestClient` |

All of them install and run on Python 3.14.8.

### Configuration — `app/config.py`

- `Settings(BaseSettings)` holds every variable of `.env.example`. Secrets are `SecretStr`, so they are masked in `repr` and in logs.
- Sources, in order of priority: environment variables first, then the repository-level `.env`, resolved from the file location so it works from any working directory.
- `env_ignore_empty=True`: the `KEY=` placeholders of `.env.example` count as "not set" and fall back to defaults or `None`.
- `extra="ignore"`: Compose-only variables such as `APP_PORT` are allowed in `.env`.
- Validation: `SPOTIFY_MARKET` must match `^[A-Z]{2}$`; `HISTORY_EXCLUDE_LAST_N ≥ 0`; enum-like values (`APP_ENV`, `LOG_LEVEL`, `STT_PROVIDER`) are `Literal` types.
- Derived properties: `database_path` / `database_url`, `stt_enabled` (provider `openai` **and** an OpenAI key), `langsmith_enabled` (flag **and** key), `spotify_configured`, `youtube_configured`, `secret_values()`.
- `get_settings()` is cached. The app keeps its settings on `app.state.settings`; tests pass their own instance to `create_app(settings)`.

### Application factory — `app/main.py`

- `create_app(settings=None)` is run with `uvicorn app.main:create_app --factory`. There is no module-level app object, so importing the module has no side effects.
- `lifespan`:
  1. runs the Alembic migrations (`upgrade head`);
  2. creates the async engine and the session factory;
  3. disposes the engine on shutdown.
- CORS is **development-only** (`CORS_ORIGINS`, default `["http://localhost:5173"]`). In production nginx serves the SPA from the same origin.
- A request logging middleware logs method, path, status, `duration_ms` and `request_id`, and sets the `X-Request-ID` response header (generated, or propagated from the request). `/api/health` is logged at DEBUG, so Docker healthchecks do not flood the log.
- All routes are under `/api`, including the OpenAPI schema (`/api/openapi.json`) and Swagger UI (`/api/docs`). The nginx `/api` proxy in step 9 then covers them too.

### Logging — `app/logging_config.py`

- The root handler gets one of two formatters:
  - **development**: readable lines, with `extra=` fields appended as `key=value`;
  - **production**: one JSON object per line, with `extra=` fields as top-level keys.
- **Secret redaction runs on the final formatted string**, so it covers the message, its arguments, `extra=` fields and exception tracebacks alike. Two layers:
  1. the exact values of all configured secrets (minimum length 8, so short values do not mask ordinary words);
  2. regular expressions for common key shapes, even if they are not configured: `sk-…` (OpenAI/Anthropic), `lsv2_…` (LangSmith), `AIza…` (Google), `Bearer …`.
- Uvicorn's loggers are routed through the root handler. `uvicorn.access` is disabled because our middleware replaces it. Uvicorn's `color_message` extra (an ANSI-colored copy of the message) is dropped.

### Errors — `app/errors.py`

- Every error has the shape `{"error": {"code", "message", "details"?}}`.
- `AppError` base class plus `NotFoundError` (404 `not_found`), `LLMUnavailableError`, `CatalogUnavailableError` and `STTUnavailableError` (503 `llm_unavailable` / `catalog_unavailable` / `stt_unavailable`).
- Framework errors are mapped to the same shape:
  - unknown route → 404 `not_found`;
  - wrong method → 405 `method_not_allowed`;
  - other HTTP errors → `http_error`;
  - request validation → 422 `validation_error`, with `details`. The echoed `input` is removed from each detail, because it may contain the user's whole text or an uploaded file.
- Unhandled exceptions return a generic 500 `internal_error` without internals. They are logged with the traceback, which is redacted.

### Endpoints — `app/api/system.py`

| Endpoint | Response |
|----------|----------|
| `GET /api/health` | `{"status": "ok", "database": "ok"}` after a `SELECT 1`; HTTP 503 `{"status": "unavailable", "database": "error"}` if the database fails |
| `GET /api/meta` | `app` (name, version, environment), `llm` (`provider:model` per tier and fallback, `heavy_reasoning`), `stt` (enabled, provider), `catalogs` (spotify, youtube configured), `langsmith` (enabled, project), `locales` (`["en", "pl"]`). **No secrets.** |

### Database — `app/db/`

- `base.py`:
  - `Base` with a **naming convention** for constraints, so names are deterministic (needed for Alembic batch mode on SQLite);
  - `UTCDateTime`, a type decorator that stores naive UTC (SQLite has no time zones), returns timezone-aware UTC, and **rejects naive datetimes**.
- `models.py`: the three tables from plan section 2.5.
  - `recommendations`: the id is a string UUID (it will also be the LangSmith run id). `status` and `input_mode` are `StrEnum`s stored as VARCHAR with a CHECK constraint. `need_profile` and `models_used` are JSON. There are indexes on `created_at` (history, exclusion list) and `spotify_track_id`.
  - `feedback`: FK to `recommendations` with `ON DELETE CASCADE` and an index; CHECK `score IN (0, 1)`; `synced_to_langsmith` flag.
  - `track_link_cache`: primary key is the normalized `artist|title`. Spotify and YouTube results have separate "fetched at" timestamps (see "Deviations").
- `session.py`: async engine (aiosqlite) with per-connection pragmas `foreign_keys=ON` (SQLite does not enforce FKs otherwise) and `journal_mode=WAL` (readers do not block on a writer).
- `migrate.py` builds the Alembic configuration in code, not from `alembic.ini`, so it works from any working directory. It runs `upgrade head` in a worker thread (`asyncio.to_thread`), keeping it off the event loop.
- `migrations/env.py`:
  - migrations use the **synchronous sqlite3 driver**;
  - the URL comes from `app.db.migrate` (startup, tests) or from the settings (CLI);
  - `render_as_batch=True`;
  - `render_item` renders app types as plain SQLAlchemy types;
  - the ini logging config is only applied for the CLI, so it does not override the app's logging on startup.
- `migrations/versions/0001_initial_schema.py`: autogenerated, then corrected by hand (see "Issues").
- `alembic.ini` exists for the CLI. Post-write hooks run `ruff format` and `ruff check --fix` on new revision scripts.

### Tests — `backend/tests/` (44 tests)

- `conftest.py`: an autouse fixture removes every settings variable from the process environment, so the developer's shell cannot change test results. `make_settings()` ignores the repository `.env` and points `DATA_DIR` to a temporary directory.
- `test_config.py`:
  - defaults, `.env` parsing, and empty values counted as unset;
  - environment beats `.env`; market validation; secrets hidden in `repr`;
  - the derived flags;
  - **`.env.example` itself is a valid configuration**.
- `test_system_api.py`:
  - health ok and health 503 (through a dependency override);
  - DB file and schema created on startup; startup is idempotent;
  - request id generated or propagated;
  - meta with nothing configured, and meta with everything configured, checking that no secret appears in the response;
  - docs under `/api`; CORS only in development.
- `test_errors.py`: the shared shape for app errors, unknown route, wrong method, validation (no echoed input) and unhandled errors (generic body, logged, redacted).
- `test_logging.py`: redaction by value and by pattern, short values not redacted, JSON and console formatters including extras and exception text, `color_message` dropped.
- `test_db.py`:
  - **migrations match the models** (`compare_metadata` is empty);
  - defaults; aware-UTC round trip; naive datetimes rejected; JSON columns;
  - FK enforcement; `ON DELETE CASCADE` at the database level;
  - enum and score CHECK constraints.

## Deviations from the plan

| Plan | Actual | Reason |
|------|--------|--------|
| `GET /api/health` → `{status}` | `{status, database}`; HTTP 503 when the DB is unreachable | Makes the Docker healthcheck (step 9) meaningful. |
| `GET /api/meta`: tiers, STT, LangSmith | Also `app`, `catalogs`, `locales` | The frontend needs the supported locales and whether the links can be verified. |
| `recommendations` columns as in plan section 2.5 | Added `album_art_url`, `need_summary`, `error_code` | `album_art_url` and `need_summary` are part of the `Recommendation` response and the history view; `error_code` records why a run failed. |
| `track_link_cache.fetched_at` | `spotify_fetched_at` and `youtube_fetched_at`, plus the canonical Spotify title and artist | YouTube is searched only for the final pick (to save quota), so one row can have Spotify data but no YouTube lookup yet. A set `youtube_fetched_at` with an empty video id means "searched, nothing found". |
| `httpx` as the test client | `httpx2` | Starlette 1.7 deprecates `httpx` in `TestClient` in favour of `httpx2` (it raised a `StarletteDeprecationWarning`). |
| — | New setting `CORS_ORIGINS` | Development CORS origins should be configurable; documented in `.env.example`. |
| — | `LANGSMITH_TRACING` defaults to `false` when unset | It is safe not to send data to the cloud unless asked. `.env.example` still sets it to `true`. |

## Issues encountered and how they were solved

1. **Autogenerate wrote `app.db.base.UTCDateTime()` into the migration without importing it.** That gave undefined-name errors, and a revision script that depends on application code breaks when the code changes. Solved with `render_item` in `env.py`, which renders `UTCDateTime` as `sa.DateTime()` (the same storage type).
2. **Every enum CHECK constraint was rendered twice.** One copy was named after the enum (`input_mode`), the other after the naming convention (`ck_recommendations_input_mode`). On top of that, `sa.Enum(create_constraint=True)` in the script would have added a third one when the table was created. The migration was fixed by hand: only the convention-named constraints are kept, and the script uses `sa.Enum(create_constraint=False)`. Checked against the real `sqlite_master` schema (one constraint each), with `alembic check` (no drift) and with `test_migrations_match_models`. The workaround is documented in `backend/README.md` for future migrations.
3. **The post-write hooks ran `ruff check` before `ruff format`.** Lines that the formatter would wrap were reported as too long. Swapped the order: format, then check.
4. **ruff sorted `app` imports as third-party.** `src = ["app", "tests"]` from step 0 means "look *inside* these directories", so `app` itself was not recognised. Changed to `src = ["."]` and an explicit `known-first-party = ["app", "tests"]`. This is a fix of a step 0 setting.
5. **mypy rejected `Settings(_env_file=...)`** (`Unexpected keyword argument`). Enabled the `pydantic.mypy` plugin (`init_typed`, `init_forbid_extra`), which also gives stricter checking of model constructors.
6. **Starlette 1.7 deprecation warning for `httpx` in `TestClient`.** Replaced the dev dependency with `httpx2`; the warning is gone.
7. **The log-capture test saw no output** with either `capsys` or `capfd`. The `StreamHandler` keeps the `sys.stderr` object it was created with, before pytest's per-test capture starts. The test now points the configured handler at a `StringIO` (`handler.setStream`), so the real formatter and redactor are still under test.
8. **Uvicorn adds an ANSI-colored `color_message` to its records.** It appeared as an extra field in both formats (seen during the live smoke test). It is now excluded.
9. **Alembic inside an async lifespan.** Alembic's async `env.py` template calls `asyncio.run()`, which cannot run inside the server's event loop. Migrations therefore use the synchronous driver and run in a worker thread.

## Consequences

- **Provider SDKs read keys from `os.environ`, but `Settings` reads `.env` without exporting it.** This matters in two places:
  - Step 2: model clients must get their API keys **explicitly** from `Settings` (`api_key=`).
  - Step 4: LangSmith must be configured explicitly (a client built from `Settings`, or the `LANGSMITH_*` values exported at startup). Otherwise tracing silently does nothing when the values only live in `.env`.
- The test client uses `httpx2`. The provider SDKs (e.g. `openai`) will bring classic `httpx` as their own dependency. For the catalog clients and their mocking in step 3, the HTTP library is chosen then: `httpx` + `respx` as planned, unless `httpx2` turns out to be the better fit by that time.
- Starlette 1.x has no `on_startup`/`on_shutdown`; everything must go through `lifespan`.
- The LangGraph checkpoint database (`checkpoints.db`) is not created yet; it comes with the graph in step 4.
- Every later model change needs an Alembic revision that passes `alembic check` and `test_migrations_match_models`.

## Verification

Run on 2026-10-07 in `backend/`:

| Command | Result |
|---------|--------|
| `uv run pytest -q` | 44 passed, no warnings |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 25 files already formatted |
| `uv run mypy` | Success: no issues found in 26 source files |
| `uv run alembic upgrade head` → `downgrade base` → `upgrade head` (temporary DB) | Applies, reverts and re-applies cleanly |
| `uv run alembic check` | No new upgrade operations detected |
| Live: `uvicorn app.main:create_app --factory` with `APP_ENV=development` and `production`, temporary `DATA_DIR`, a dummy `OPENAI_API_KEY` | `app.db` created on startup; `/api/health` → `{"status":"ok","database":"ok"}`; `/api/meta` correct (STT enabled because of the key); `/api/nope` → `{"error":{"code":"not_found",…}}`; readable logs in development, JSON lines in production; the dummy key appears **0 times** in the logs |
