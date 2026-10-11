# ADR-11.1: Step 11 — Anonymous visitors, per-visitor history and daily limits

- Status: Accepted
- Date: 2026-10-11
- Step: 11 (additional ADR #1)
- Amends: [ADR-05](step-05-recommendation-api.md) (the history and feedback endpoints are now
  scoped to a visitor), [ADR-06](step-06-speech-to-text.md) (transcriptions count towards a
  daily limit), NFR-1 in [requirements](../requirements.md)

## Context

The app was built for one local user (NFR-1). Before it is shared publicly for testing, with
one OpenAI key and a small prepaid budget, two gaps had to close:

1. **Shared history.** `GET /api/recommendations` returned every completed request with its
   verbatim `input_text`, so each visitor could read everyone else's description of their day.
2. **No usage limits.** One visitor could start an unlimited number of recommendations and
   transcriptions and use up the whole budget.

The requirement was: fix the history leak, and allow **10 requests per user per day**. There
are no accounts, so "user" had to be defined. This is a cross-cutting change (backend API, STT
endpoint, database, frontend, nginx), so it is numbered under the most recently finished step.

## Decision / What was implemented

### Visitor identity: a random id in an HttpOnly cookie

- `app/api/visitors.py`: the `identify_visitor` middleware reads the `sr_visitor` cookie; when
  it is missing or not an id this module issued (43 URL-safe characters), it issues a new one
  (`secrets.token_urlsafe(32)`, 256 bits). The id is in `request.state.visitor_id`, read by the
  `VisitorDep` dependency.
- Cookie attributes: `HttpOnly` (the page's scripts never need it), `SameSite=Lax`,
  `Path=/api`, `Max-Age` 400 days (the longest browsers accept), `Secure` when the request
  scheme is HTTPS.
- No frontend change is needed for identity: the SPA and the API share an origin, so `fetch`
  sends the cookie by default.
- The visitor id is never logged and never sent to LangSmith: whoever holds it can read that
  visitor's history.

### Per-visitor data

- `recommendations.visitor_id` (nullable, indexed), written by `RecommendationRunner.start`.
- `GET /api/recommendations` lists only the visitor's completed recommendations (and counts
  only those in `total`).
- `POST …/clarification` and `POST …/feedback` check ownership first (`_owned` in
  `app/api/recommendations.py`); another visitor's id is answered with `404 not_found`, the
  same as an unknown id, so ids cannot be probed.
- The exclusion list (`HISTORY_EXCLUDE_LAST_N`) is per visitor too: songs another visitor got
  are no longer excluded for you. This follows from "history" now meaning one visitor's history.

### Daily limits

- New table `daily_usage (visitor_id, day, action, used)`, primary key on the first three;
  `action` is `recommendation` or `transcription`.
- `UsageRepository.try_use` is a single SQLite upsert:
  `INSERT … ON CONFLICT DO UPDATE SET used = used + 1 WHERE used < :limit RETURNING used`.
  No row returned = limit reached. Checking and counting in one statement means concurrent
  requests cannot both take the last use, without an application lock.
- `app/api/limits.py` (`DailyLimits`) maps settings to actions and raises
  `DailyLimitReachedError` → `429 daily_limit_reached`.
- Settings (`.env`): `DAILY_RECOMMENDATION_LIMIT=10`, `DAILY_TRANSCRIPTION_LIMIT=20`; `0`
  turns a limit off. Days are UTC days.
- What counts: a new recommendation (`POST /api/recommendations`), counted after request
  validation and before the graph runs. Answering a clarifying question does **not** count; it
  finishes the same request. A transcription counts after the format, size and emptiness
  checks, before the provider call. Invalid requests never count.

### Frontend and proxy

- `daily_limit_reached` is a known error code with EN/PL messages ("You have used today's limit
  for this test version. Please come back tomorrow.").
- The History page says "Only recommendations made in this browser are shown."
- `frontend/nginx.conf` passes the incoming `X-Forwarded-Proto` to the backend (falling back
  to its own `$scheme`), so behind a TLS-terminating tunnel the backend sees HTTPS and marks the
  cookie `Secure`.

### Migration

`0003_visitors_and_daily_usage`: creates `daily_usage` and adds `recommendations.visitor_id`
with its index. Existing rows keep `visitor_id = NULL`.

## Deviations from the plan

- NFR-1 ("single user, no authentication") is amended: still no accounts or login, but each
  browser is an anonymous visitor. Multi-user support stays out of scope; this is the minimum
  for a public test.
- The request was "10 per user per day". Transcriptions got their own, higher limit (20)
  instead of sharing the 10: a voice recommendation is one transcription plus one
  recommendation, and people often record again before submitting. Without any transcription
  limit, the audio endpoint would be an unlimited way to spend the budget.

## Issues encountered and how they were solved

- **Defining "user" without accounts.** Options were a header from `localStorage`, a
  server-issued cookie, or the client IP. The IP was rejected as the identity: mobile carriers
  put many people behind one address (CGNAT), and behind a Cloudflare Tunnel every request
  arrives from the tunnel container unless nginx is configured to trust `CF-Connecting-IP`. A
  server-issued `HttpOnly` cookie needs no frontend code and cannot be read by page scripts.
- **The limit can be reset by a new visitor.** A private window or cleared cookies give a new
  id with fresh limits. Accepted for a test deployment: the limit stops casual overuse, and the
  OpenAI project's hard spend limit stays the real ceiling. A per-IP backstop is a possible
  follow-up once the deployment's real-IP setup (tunnel + nginx `real_ip`) exists.
- **Race on the last allowed request.** A count-then-insert check would let parallel requests
  all pass. Solved with the single conditional upsert described above.
- **`Secure` cookie and local HTTP.** Some browsers do not send `Secure` cookies back over
  `http://localhost`, so the flag is set only when the request is HTTPS. Behind nginx the scheme
  was always `http`, which is why nginx now forwards the upstream `X-Forwarded-Proto`. A forged
  header can only add the `Secure` flag to that client's own cookie.
- **Testing the HTTPS case.** `TestClient` does not run uvicorn's proxy-header handling, so the
  test uses `base_url="https://testserver"`; the real chain was checked with a local uvicorn
  started with `--proxy-headers --forwarded-allow-ips '*'` (see Verification).
- **Ambiguous cookies in tests.** Setting a cookie by hand in the `TestClient` jar and
  receiving one with `Path=/api` gave two cookies of the same name (`CookieConflict` on read);
  the forged-cookie test checks the `Set-Cookie` header instead.
- **Old history disappears from the UI.** Rows from before this change have no visitor, so no
  browser lists them. They stay in `data/app.db`; no automatic adoption was added, because
  on a public server it would hand the old history to the first visitor.

## Consequences

- The app can be shared publicly without visitors reading each other's descriptions.
- Each browser can start 10 recommendations and 20 transcriptions per UTC day; local users can
  set both limits to `0`.
- `daily_usage` grows by at most two rows per visitor per active day; it is not pruned yet.
- A failed recommendation (e.g. provider outage) still uses one of the day's 10.
- Follow-ups for a public deployment (see the deployment guide): nginx rate limiting by real
  client IP, a privacy note on the home page, `/api/docs` off in production.

## Verification

```bash
cd backend
uv run pytest -q                 # 344 passed
uv run ruff check . && uv run ruff format --check .
uv run mypy .                    # no issues in 90 source files
cd ../frontend
npm test                         # 66 passed
npm run lint && npm run typecheck && npm run format:check
docker run --rm -v "$PWD/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  --add-host backend:127.0.0.1 nginx:1.30-alpine nginx -t   # syntax is ok
```

New tests: `tests/test_visitors.py` (cookie attributes, reuse, forged id, `Secure` over HTTPS),
visitor and limit tests in `tests/test_recommendations_api.py` (own history only, 404 for
another visitor's clarification and feedback, per-visitor exclusions, limit reached without an
LLM call, clarification not counted, per-visitor and per-day counters, invalid requests not
counted, `0` = no limit), `test_daily_limit_stops_transcriptions`, repository tests for
`try_use`, `recent_tracks` and `list_completed` per visitor, and frontend tests for the limit
message and the history note.

Manual check: uvicorn with `--proxy-headers --forwarded-allow-ips '*'` on an empty data
directory; `GET /api/recommendations` returned an empty page and
`Set-Cookie: sr_visitor=…; HttpOnly; Max-Age=34560000; Path=/api; SameSite=lax`, and with
`X-Forwarded-Proto: https` the same plus `; Secure`.
