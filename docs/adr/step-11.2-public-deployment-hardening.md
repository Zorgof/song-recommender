# ADR-11.2: Step 11 — Public deployment hardening and Cloudflare Tunnel

- Status: Accepted
- Date: 2026-10-12
- Step: 11 (additional ADR #2)
- Amends: [ADR-09](step-09-docker.md) (the app port is bound to `127.0.0.1`; nginx gets rate
  limits and real client IPs; a tunnel override), [ADR-11.1](step-11.1-visitors-and-daily-limits.md)
  (daily limits of all visitors together on top of the per-visitor ones)

## Context

The app is about to be shared with testers from the developer's PC through a Cloudflare Tunnel,
paid for by one OpenAI project with a hard spend limit of $6. ADR-11.1 closed the history leak
and added per-visitor daily limits. The deployment guide listed what was still open before the
link can be shared:

- **Should do:** a privacy notice on the home page; `/api/docs` and `/api/openapi.json` off in
  production; separate keys and a separate LangSmith project for the deployment.
- **Still open from "Must fix":** nginx rate limiting by the real client IP (behind a tunnel
  every request comes from the tunnel); a ceiling for all visitors together, since a private
  window resets the per-visitor limit; a clear message when the OpenAI budget is used up,
  instead of a generic "provider unavailable".
- **Server basics:** publish nothing but the tunnel; `.env` readable by the owner only.

This is a cross-cutting change (backend, frontend, nginx, Compose, docs), so it is numbered
under the most recently finished step.

## Decision / What was implemented

### API docs off in production

`create_app` sets `docs_url` and `openapi_url` only when `APP_ENV=development`. Docker Compose
sets `production`, so `/api/docs` and `/api/openapi.json` answer `404 not_found` there.

### Budget exhausted (`503 budget_exhausted`)

- `app/llm/budget.py`: `is_budget_exhausted(exc)` walks the exception chain (`__cause__`,
  `__context__`) for an `openai.APIError` whose `code` is `project_spend_limit_exceeded`,
  `organization_spend_limit_exceeded`, `credit_balance_exhausted` or `insufficient_quota`.
- `structured_call` raises `BudgetExhaustedError` instead of `LLMUnavailableError` for those, and
  logs `LLM budget is used up` at ERROR. A configured fallback model is still tried first (the
  fallback wrapper runs before the error reaches `structured_call`), so a fallback on another
  provider keeps the app working.
- `OpenAISTT` does the same for transcriptions instead of `STTUnavailableError`.
- HTTP 503: the server, not the client, is out of capacity; trying again does not help until
  the budget is raised or the month ends.

### Daily limits of all visitors together (`503 daily_capacity_reached`)

- Settings `DAILY_TOTAL_RECOMMENDATION_LIMIT=100` and `DAILY_TOTAL_TRANSCRIPTION_LIMIT=200`
  (`0` = off).
- `DailyLimits.use` counts in the same `daily_usage` table, under the key `"*"` (visitor ids are
  URL-safe base64, which has no `*`), with the same atomic upsert as ADR-11.1. No migration.
- The visitor's own limit is checked first: a visitor already over their limit is rejected
  before touching the shared counter, so they cannot use up other visitors' day.

### nginx: real client IP and rate limits

- `set_real_ip_from` the private ranges (10/8, 172.16/12, 192.168/16, 127.0.0.1) with
  `real_ip_header CF-Connecting-IP`. The `tunnel` container reaches nginx from the Compose
  network, and Cloudflare's edge always sets that header itself, so `$remote_addr` becomes the
  visitor's address. Without a tunnel the header is absent and nothing changes.
- `limit_req_zone expensive` (6 per minute, burst 6, `nodelay`) keyed by the client IP only for
  `POST /api/recommendations` and `POST /api/transcriptions` (a `map` on method and URI gives
  other requests an empty key, which nginx does not count). `limit_req_zone api` (5 per second,
  burst 30) on all of `/api`.
- Rejections are `429` with the API's error shape, `{"error":{"code":"rate_limited",…}}`, and
  `Retry-After: 60`. The backend's own `429 daily_limit_reached` passes through unchanged
  (`proxy_intercept_errors` is off).

### Compose: localhost only, tunnel as a service

- `docker-compose.yml` publishes the frontend on `127.0.0.1:${APP_PORT}` instead of all
  interfaces. Docker's port publishing bypasses the host firewall, so the bind address is the
  only reliable way to keep the port private.
- `docker-compose.public.yml` adds a `tunnel` service, `cloudflare/cloudflared:2026.9.3`
  (pinned), running a Quick Tunnel to `http://frontend:80`. The named-tunnel variant
  (`tunnel run` + `TUNNEL_TOKEN`) is in the same file as commented lines. `docker compose stop
  tunnel` is the kill switch.

### Frontend

- Home page: one sentence under the tagline, EN and PL, saying that descriptions and recordings
  go to OpenAI (USA), descriptions also to LangSmith (USA) and are stored on the server, and
  asking not to enter personal data (NFR-5).
- New error codes with EN/PL messages: `budget_exhausted`, `daily_capacity_reached`,
  `rate_limited`.
- `canRetry(error)`: no "Try again" button for `daily_limit_reached`, `daily_capacity_reached`
  and `budget_exhausted`, where retrying the same day cannot help. `rate_limited` keeps it.

### Configuration and docs

- `.env.example`: the two total limits with a sizing hint, a commented `TUNNEL_TOKEN`, and a
  note to use a separate LangSmith project for a public deployment.
- The developer's `.env`: `LANGSMITH_PROJECT=song-recommender-public`, `chmod 600`. The new
  OpenAI key in its own capped project was set up by the developer beforehand.
- New [docs/deployment.md](../deployment.md) (runbook: keys, Quick Tunnel, named tunnel, sizing
  the limits, kill switch, backup); configuration, architecture, troubleshooting and README
  updated.

## Deviations from the plan

- The deployment guide suggested running `cloudflared` installed in WSL. It runs as a Compose
  service instead: nothing to install, it starts and stops with the stack, it reaches nginx
  from a private address (needed for `CF-Connecting-IP` to be trusted), and `stop tunnel` is
  an exact kill switch.
- The guide's rate limit was 5 per minute. It is 6 per minute with a burst of 6: a voice
  recommendation is a transcription plus a recommendation, often recorded twice.
- Cloudflare Turnstile (optional in the guide) is not added; worth it only if the rate limits
  are actually hit.
- A separate Spotify Client ID is left to the developer (Spotify dashboard).

## Issues encountered and how they were solved

- **Which IP nginx sees.** Behind a tunnel every request comes from the `cloudflared`
  container, so a per-IP limit would be one limit for everyone. Trusting `CF-Connecting-IP`
  from any client would let anyone pick their own IP. Solved by trusting it only from private
  addresses, which the outside world cannot reach once the port is bound to `127.0.0.1`.
- **Rate-limiting only two POST endpoints without repeating the proxy block.** A nested
  `location` would need its own `set $backend` / `proxy_pass` (rewrite-phase directives are not
  inherited). A `map` on `"$request_method $uri"` gives every other request an empty key
  instead, and nginx does not count empty keys.
- **`add_header` in the `@rate_limited` location** replaces the server-level headers, so
  `X-Content-Type-Options` is repeated there, as in the other locations.
- **Ordering of the two daily counters.** Counting the shared total first would let a visitor
  over their own limit drain it with rejected requests; the visitor's counter goes first.
  The cost: when the total is reached, the rejected request still used one of that visitor's
  own uses, which only matters on a day the app is closed anyway.
- **Empty `TUNNEL_TOKEN` and the Quick Tunnel.** Passing an empty token variable to
  `cloudflared` in Quick Tunnel mode risked it being read as a set, empty flag; the variable
  is only in the commented named-tunnel lines.
- **Validating the nginx and Compose changes.** Docker Desktop was not running, and its WSL
  integration was off, while the changes were made; both checks below were run once Docker was
  available and passed.

## Consequences

- The stack can be shared from the PC with `docker compose -f docker-compose.yml -f
  docker-compose.public.yml up --build -d`; the address is in the `tunnel` logs.
- Local use is unchanged at `http://localhost:8080`, but other devices on the LAN can no longer
  open `http://<ip>:8080` (the tunnel replaces it).
- On a day with 100 recommendations from all visitors, everyone gets `daily_capacity_reached`
  until midnight UTC. The value should be sized to the budget after measuring the cost of one
  recommendation (docs/deployment.md).
- Follow-ups: the result card still shows "View trace in LangSmith", which testers cannot
  open (it needs the developer's LangSmith login); `daily_usage` is not pruned; a daily backup
  of `data/app.db` is documented, not scheduled.

## Verification

```bash
cd backend
uv run pytest -q                 # 354 passed
uv run ruff check . && uv run ruff format --check .
uv run mypy .                    # no issues in 91 source files
cd ../frontend
npm test                         # 70 passed
npm run lint && npm run typecheck && npm run format:check
```

New tests: `test_openapi_docs_are_hidden_in_production`; `test_spend_limit_is_budget_exhausted`,
`test_working_fallback_wins_over_spend_limit`, `test_ordinary_rate_limit_is_unavailable`
(structured calls); `test_spend_limit_is_budget_exhausted` for each OpenAI code (STT);
`test_daily_total_limit_stops_every_visitor`,
`test_visitor_over_own_limit_does_not_use_up_the_total`,
`test_daily_total_limit_stops_transcriptions_of_all_visitors`; frontend tests for the privacy
note, the three new messages and when "Try again" is offered.

With Docker Desktop started (both passed: `syntax is ok`, `test is successful`; config valid):

```bash
docker run --rm -v "$PWD/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  --add-host backend:127.0.0.1 nginx:1.30-alpine nginx -t
docker compose -f docker-compose.yml -f docker-compose.public.yml config --quiet
```
