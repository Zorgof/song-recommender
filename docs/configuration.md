# Configuration

All configuration goes through environment variables, normally from the `.env` file in the
repository root (FR-61). Start from the documented template:

```bash
cp .env.example .env
```

- The backend reads `.env` itself (pydantic-settings) when it runs on the host, and receives it
  through `env_file` when it runs in Docker. Environment variables set in the shell win over
  `.env`.
- An empty line such as `ANTHROPIC_API_KEY=` counts as **not set**, so the default applies.
- Keys are only ever used by the backend. They are never sent to the browser and are redacted
  from the logs.
- Changes take effect when the backend restarts (`docker compose up -d` recreates the container
  when `.env` changed; with `--reload` on the host, restart it yourself).

## Application

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | `development`: readable console logs, CORS for `CORS_ORIGINS`. `production`: JSON logs, no CORS. **Docker Compose sets `production`** (the dev override sets `development`) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `DATA_DIR` | `data` | Directory of `app.db` and `checkpoints.db`. Relative paths are relative to the working directory: `backend/data` when you run the backend from `backend/`. **Docker Compose sets `/data`**, mounted from `./data` |
| `HISTORY_EXCLUDE_LAST_N` | `50` | Songs from this many recent recommendations are not recommended again (FR-16); `0` turns it off |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | JSON list of origins allowed to call the API directly; `development` only. Not needed with the Vite proxy |
| `APP_PORT` | `8080` | Docker Compose only: host port of the app (`http://localhost:<APP_PORT>`) |

## Language models

Each tier is a `provider:model` string. Providers: `openai`, `anthropic`, `google_genai`. Both
tiers are required; the backend refuses to start with a message that lists every problem (a
missing tier, a malformed value, a missing key).

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_LIGHT` | — (required) | Light tier: the routing classifier, and both agents for simple requests |
| `LLM_HEAVY` | — (required) | Heavy tier: both agents for complex requests, retries after invalid output, curator retries after unverified songs, and the eval judge |
| `LLM_LIGHT_FALLBACK` | — | Optional model tried when the light tier's provider fails |
| `LLM_HEAVY_FALLBACK` | — | Optional model tried when the heavy tier's provider fails |
| `LLM_HEAVY_REASONING` | `off` | `on` turns on provider-native reasoning for the heavy tier, effort "medium". OpenAI also returns reasoning summaries, visible in LangSmith |
| `LLM_TIMEOUT_SECONDS` | `60` | Timeout of one request to a model provider (also used for transcription) |
| `LLM_MAX_RETRIES` | `2` | Retries of a failed provider request, done by the provider SDK (also used for transcription) |
| `OPENAI_API_KEY` | — | Required if a tier or fallback uses `openai`, and for speech-to-text |
| `ANTHROPIC_API_KEY` | — | Required if a tier or fallback uses `anthropic` |
| `GOOGLE_API_KEY` | — | Required if a tier or fallback uses `google_genai` (Gemini API key) |

Model ids are passed to the provider as they are. The startup check validates the format and
the keys, not whether the model exists: a wrong id shows up on the first request as
`llm_unavailable` (see [Troubleshooting](troubleshooting.md#the-language-model-is-unavailable-right-now-llm_unavailable)).

Examples (tiers may use different providers):

```bash
# OpenAI (the default configuration)
LLM_LIGHT=openai:gpt-6-luna
LLM_HEAVY=openai:gpt-6.1-sol

# Anthropic
LLM_LIGHT=anthropic:claude-haiku-5-5
LLM_HEAVY=anthropic:claude-sonnet-5-5

# Google Gemini
LLM_LIGHT=google_genai:gemini-3.5-flash-lite
LLM_HEAVY=google_genai:gemini-3.8-flash

# Mixed, with a fallback for the heavy tier
LLM_LIGHT=openai:gpt-6-luna
LLM_HEAVY=anthropic:claude-sonnet-5-5
LLM_HEAVY_FALLBACK=openai:gpt-6.1-sol
```

OpenAI is the configuration tested end to end. The Anthropic and Gemini configurations are
tested offline (model construction, structured-output setup); see
[ADR-02.1](adr/step-02.1-anthropic-structured-output.md).

## Speech-to-text

| Variable | Default | Description |
|----------|---------|-------------|
| `STT_PROVIDER` | `openai` | `openai`, or `none` to switch voice input off (the UI hides the microphone, FR-32). Without `OPENAI_API_KEY` STT is off too |
| `STT_MODEL` | `gpt-transcribe` | OpenAI transcription model. `gpt-transcribe` reports the detected language; `gpt-4o-mini-transcribe` and `whisper-1` also work (without the language) |

## Music catalogs

| Variable | Default | Description |
|----------|---------|-------------|
| `SPOTIFY_CLIENT_ID` | — | Spotify app credentials (Client Credentials flow) for verifying songs, links, album art and the player. Without them recommendations are unverified |
| `SPOTIFY_CLIENT_SECRET` | — | |
| `SPOTIFY_MARKET` | `PL` | ISO 3166-1 alpha-2 country whose catalog is searched |
| `YOUTUBE_API_KEY` | — | Google Cloud API key with "YouTube Data API v3" enabled. Without it, YouTube links are search links. The free quota is about 100 searches a day |
| `CATALOG_TIMEOUT_SECONDS` | `10` | Timeout of one request to Spotify or YouTube |

Getting the credentials:

- **Spotify:** create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
  (the account that owns the app needs Spotify Premium). The form asks for a redirect URI; it
  is not used, so any valid one works, e.g. `http://127.0.0.1:8080/callback`. Copy the Client
  ID and Client secret. Development Mode is enough; it limits search results to 10 per query,
  which the app respects.
- **YouTube:** in the [Google Cloud console](https://console.cloud.google.com/), enable
  "YouTube Data API v3" for a project, then create an API key under Credentials (restricting it
  to that API is recommended).

## LangSmith

| Variable | Default | Description |
|----------|---------|-------------|
| `LANGSMITH_TRACING` | `false` (`.env.example`: `true`) | `true` sends a trace per recommendation and user ratings as feedback. The app works with it off |
| `LANGSMITH_API_KEY` | — | Personal access token (`lsv2_pt_…`) or service key (`lsv2_sk_…`) from LangSmith → Settings → API Keys |
| `LANGSMITH_WORKSPACE_ID` | — | Workspace UUID; **required for organization-scoped service keys** (`lsv2_sk_…`), which otherwise get HTTP 403. Optional for personal tokens |
| `LANGSMITH_PROJECT` | `song-recommender` | Tracing project; created on the first trace |
| `LANGSMITH_ENDPOINT` | `https://api.smith.langchain.com` | US region (FR-46) |

These settings are passed to the LangSmith client explicitly (like every setting, they can
also come from the shell). Other tracing variables, such as `LANGCHAIN_TRACING_V2` or
`LANGCHAIN_PROJECT`, are not used: with `LANGSMITH_TRACING=false` nothing is traced even if they
are set.

## Development and Docker only

| Variable / option | Where | Description |
|-------------------|-------|-------------|
| `API_PROXY_TARGET` | environment of `npm run dev` | Where the Vite dev server proxies `/api` (default `http://localhost:8000`); set to `http://backend:8000` by `docker-compose.dev.yml` |
| `COMPOSE_FILE` | shell | `docker-compose.yml:docker-compose.dev.yml` makes plain `docker compose …` use the dev override |
| `APP_UID`, `APP_GID` | build args of `backend/Dockerfile` | uid/gid of the backend's user (default 1000); `./data` must be writable by it |

## Evaluation options

The evaluation CLI (`uv run python -m evals.run_evals`) uses the same `.env` and needs
LangSmith enabled. Its options (`--limit`, `--repetitions`, `--judge-model`, `--with-youtube`,
…) are described in [Observability and tuning](observability-and-tuning.md#running-evaluations).
