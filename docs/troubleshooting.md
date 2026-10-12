# Troubleshooting

Start with the logs: `docker compose logs -f backend` (JSON lines in Docker), or the terminal of
`uv run uvicorn …` when running on the host. Every response has an `X-Request-ID` header that
also appears in the backend's request log line.

## Starting the app

### The backend does not start: "Invalid LLM configuration"

```
Invalid LLM configuration:
  - LLM_HEAVY is not set (expected provider:model, e.g. openai:<model>)
  - ANTHROPIC_API_KEY is required by LLM_LIGHT=anthropic:claude-haiku-5-5
```

The message lists every problem at once. Set both `LLM_LIGHT` and `LLM_HEAVY` as
`provider:model` (`openai`, `anthropic` or `google_genai`), and the key of every provider they
use, fallbacks included. See [Configuration](configuration.md#language-models). In Docker the
backend then restarts in a loop and the frontend waits for it; fix `.env` and run
`docker compose up -d` again.

### The backend does not start: "The data directory /data is not writable by uid 1000"

The backend runs as uid 1000 in Docker and stores its databases in `./data`. If that directory
was missing, Docker Desktop created it **owned by root**. Fix it in the repository root:

```bash
sudo chown -R 1000:1000 data
```

`./data` is part of the repository (it holds a `.gitkeep`), so this only happens after deleting
it. If your user is not uid 1000, build with your ids: `docker compose build --build-arg
APP_UID=$(id -u) --build-arg APP_GID=$(id -g) backend`.

### `docker: command not found` in WSL

Start Docker Desktop on Windows and enable *Settings → Resources → WSL integration* for your
distribution; then `docker info` must print the engine version.

### Port 8080 is already in use

Set another port in `.env`, e.g. `APP_PORT=8081`, and run `docker compose up -d`. The app is then
at `http://localhost:8081`.

### The app does not open from another device at `http://<ip>:8080`

The port is bound to `127.0.0.1` on purpose (ADR-11.2): only the host can open it directly, and
the public address comes from the Cloudflare Tunnel. Start the stack with the tunnel and open the
`https://…trycloudflare.com` address it prints; see [Deployment](deployment.md).

### LangSmith returns 403

An organization-scoped service key (`lsv2_sk_…`) needs the workspace: set
`LANGSMITH_WORKSPACE_ID` (LangSmith → Settings → Workspaces). Personal access tokens
(`lsv2_pt_…`) work without it. The app keeps working when LangSmith fails; only traces and the
"View trace" link are missing, and ratings are saved locally.

## Recommendations

### "The language model is unavailable right now" (`llm_unavailable`)

The provider call failed after the SDK's retries (and the fallback model, if configured). The
backend log has `LLM call failed` with the error type:

| Error type in the log | Usual cause |
|-----------------------|-------------|
| `NotFoundError` | the model id in `LLM_LIGHT` / `LLM_HEAVY` does not exist; the startup check validates the format, not the id |
| `AuthenticationError`, `PermissionDeniedError` | wrong or revoked key, or no access to that model |
| `RateLimitError` | quota or rate limit of the provider account |
| `APITimeoutError`, `APIConnectionError` | network problems; `LLM_TIMEOUT_SECONDS` too low for a slow model |

### "The language model returned an unusable answer" (`llm_invalid_output`)

The heavy model's output did not match the schema, after a light → heavy retry. Usually
temporary; try again. If it repeats with one model, check its trace: the LLM run shows the raw
answer. Anthropic models use Claude's native structured output
([ADR-02.1](adr/step-02.1-anthropic-structured-output.md)).

### Songs are "unverified", and there is no player

The song could not be confirmed on Spotify, so the card shows search links and no embedded
player. Causes, in the backend log:

| Log message | Cause / fix |
|-------------|-------------|
| `Spotify is not configured` (at startup) | set `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` |
| `Spotify rejected the client credentials` | wrong id or secret, or the app was deleted in the Spotify dashboard |
| `Spotify rate limit reached`, `Spotify request failed` | temporary; the next request retries |
| none of these | the curator's three attempts all named songs Spotify does not have in `SPOTIFY_MARKET`; the trace's `spotify_lookup` runs show the closest matches |

### The YouTube button opens a search instead of a video

The YouTube Data API's free quota is 10,000 units a day, and a search costs 100: about **100
searches a day**. After a quota error the log says `YouTube quota exceeded; using search links
until the quota resets`, and no YouTube call is made until midnight Pacific time. Lookups are
cached (found videos for 30 days), so repeated songs do not use quota. Without
`YOUTUBE_API_KEY` every YouTube link is a search link. The evaluation does not use YouTube unless
you pass `--with-youtube`.

### A request takes long, or fails after 2 minutes

A recommendation takes about 10–17 s; complex descriptions (long, mixed feelings) take 25–30 s
because both agents run on the heavy tier, and a curator retry adds more. nginx waits up to
**120 s** for the backend, then returns 504; if that happens, the provider is very slow:
consider a faster `LLM_HEAVY`, `LLM_HEAVY_REASONING=off`, or a lower `LLM_TIMEOUT_SECONDS`.

### "You have used today's limit" (`daily_limit_reached`)

Each browser may start `DAILY_RECOMMENDATION_LIMIT` (default 10) recommendations and transcribe
`DAILY_TRANSCRIPTION_LIMIT` (default 20) recordings per day; the counters reset at midnight
UTC. For local use, set both to `0` in `.env` to turn the limits off, then restart the backend.

### "This test version has reached today's limit for all visitors" (`daily_capacity_reached`)

All visitors together started `DAILY_TOTAL_RECOMMENDATION_LIMIT` (default 100) recommendations or
`DAILY_TOTAL_TRANSCRIPTION_LIMIT` (default 200) transcriptions today (UTC). The backend logs
`Daily limit of all visitors reached`. Raise the limit in `.env` if the budget allows, or set it
to `0` for local use, then restart the backend.

### "The budget of this test version is used up" (`budget_exhausted`)

OpenAI refused the call because the project's or organization's hard spend limit, or the prepaid
balance, is used up; the backend logs `LLM budget is used up` or `OpenAI transcription failed`
with the code. Nothing in the app can fix it: raise the limit or top up on platform.openai.com,
or wait for the next monthly cycle. Requests work again without a restart.

### "Too many requests in a short time" (`rate_limited`)

nginx limits each client IP to 6 new recommendations or recordings per minute (after a burst of 6)
and 5 API requests per second. Wait a minute. If every visitor hits it at once behind the
tunnel, nginx is not seeing the real client IP: the tunnel must reach nginx from a private
address (the `tunnel` service in `docker-compose.public.yml` does), so `CF-Connecting-IP` is
trusted.

### The history is empty, or older recommendations are missing

The history shows only the recommendations made in the current browser (it is identified by
the `sr_visitor` cookie). Another browser, a private window or cleared cookies start an empty
history. Recommendations made before visitors were introduced (ADR-11.1) are still in
`data/app.db` but belong to no browser, so they are not listed.

### "This request can no longer be continued" (`conflict`) when answering a question

The question was already answered, or the paused state is gone (e.g. `data/checkpoints.db` was
deleted). Start over with a new description.

### The same songs keep coming back

Songs from the browser's last `HISTORY_EXCLUDE_LAST_N` (default 50) recommendations are
excluded.
Beyond that, the curator tends to favour well-known songs for a mood; this is measured by the
evaluation (`distinct_songs`, `fit_specificity`) and is a prompt-tuning topic, see
[Observability and tuning](observability-and-tuning.md#changing-a-prompt).

## Voice input

### There is no microphone button

| Cause | Fix |
|-------|-----|
| STT is off: `STT_PROVIDER=none`, or no `OPENAI_API_KEY` | set `STT_PROVIDER=openai` and the key; `/api/meta` must report `"stt": {"enabled": true, …}` |
| The page is not a **secure context** (the UI says "Voice input needs a secure connection") | browsers allow the microphone only on `https://` or `http://localhost`. Open the app as `http://localhost:8080`, not by IP address |
| The browser has no `MediaRecorder` | use a current Chrome, Firefox, Edge or Safari |

### Using the microphone from another device (phone, laptop on the LAN)

Plain `http://<ip>:8080` is not a secure context, so the microphone is blocked there (NFR-4).
Options, not part of the tested setup:

- **HTTPS reverse proxy** on the host, e.g. with [Caddy](https://caddyserver.com/):

  ```bash
  caddy reverse-proxy --from https://192.168.1.20:8443 --to localhost:8080 --internal-certs
  ```

  Then open `https://192.168.1.20:8443` on the device and trust Caddy's local certificate (or
  accept the browser's warning). Use your host's LAN address, and allow the port in the
  firewall.
- **Cloudflare Tunnel** (simplest): start the stack with `docker-compose.public.yml` and open
  the `https://…trycloudflare.com` address on the device; see [Deployment](deployment.md). It
  is public, though, not limited to your LAN.

The app port itself is bound to `127.0.0.1` (ADR-11.2), so `http://<ip>:8080` does not open from
other devices at all.

### "Microphone access is blocked"

The browser denied the permission. Allow the microphone for the site (the icon in the address
bar, or the browser's site settings) and click Record again.

### "We didn't catch any speech"

The transcript was empty: the recording was silent or too quiet. Check the selected input
device in the system settings, and speak closer to the microphone.

### "The recording could not be processed" (`invalid_audio`) or "too large"

The provider could not decode the audio (corrupted or under about 0.1 s), or the file is over
10 MB. Recordings stop at 90 s, which is far below 10 MB for the formats browsers record.

### "Speech recognition is unavailable right now" (`stt_unavailable`)

The transcription call failed. The log has `OpenAI transcription failed` with the error type
and code, e.g. `model_not_found` for a wrong `STT_MODEL`, or an authentication error for the
key. "Try again" re-sends the same recording.

## Evaluation

### `LangSmith is not enabled`

`run_evals` needs `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY`.

### Examples added in the LangSmith UI disappear

The dataset is synced from `backend/evals/dataset.jsonl` on every run, and examples that are not
in the file are deleted. Add examples to the file.

### Scores differ between two runs of the same version

They do: the models are not deterministic. Compare versions with `--repetitions 2` or more.

## Development

### Frontend dev server: API calls fail

`npm run dev` proxies `/api` to `http://localhost:8000`; start the backend first. In
`docker-compose.dev.yml` the proxy target is the `backend` service (`API_PROXY_TARGET`).

### Changes do not show up in Docker

The production images contain a build of the code: run `docker compose up -d --build`. For hot
reload use the dev override: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up`.
