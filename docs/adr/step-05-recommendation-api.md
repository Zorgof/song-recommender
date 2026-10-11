# ADR-05: Step 5 — Recommendation API and history

- Status: Accepted (amended by [ADR-11.1](step-11.1-visitors-and-daily-limits.md))
- Date: 2026-10-10
- Step: 5

## Context

Step 5 of the [implementation plan](../implementation-plan.md) exposes the agent graph
(ADR-04) over HTTP for the frontend (section 2.6):
- start a recommendation;
- answer the clarifying question;
- list the history;
- rate a recommendation; the rating is stored locally and sent to LangSmith as feedback, and
  stays stored (`synced_to_langsmith=false`) when LangSmith is unavailable.

"Done when": API tests cover both response variants, resuming the graph, history paging and
feedback with LangSmith mocked.

## Decision / What was implemented

### Endpoints — `app/api/recommendations.py`

| Method and path | Body / params | Response |
|-----------------|---------------|----------|
| `POST /api/recommendations` | `{text, input_mode = "text", locale}` | `{status: "completed", recommendation}` or `{status: "needs_clarification", request_id, question}` |
| `POST /api/recommendations/{id}/clarification` | `{answer}` | the same union (in practice always `completed`) |
| `GET /api/recommendations` | `limit` 1–100 (default 20), `offset` ≥ 0 | `{items, total, limit, offset}` |
| `POST /api/recommendations/{id}/feedback` | `{score: "up" \| "down", comment?}` | `204` |

- The two response variants form a union discriminated by `status`, so the OpenAPI schema
  states it exactly.
- `recommendation` is the agents' `Recommendation` schema (ADR-04), including `trace_url`.
- Request bodies reject unknown fields. Texts are trimmed before validation and use:
  description 3–2000 characters (FR-6), answer 1–2000, comment up to 1000. `locale` is
  `en`/`pl`; `input_mode` is `text`/`voice`.
- **History** contains completed recommendations only, newest first (`created_at`, then id).
  Each item has the input, the clarification question and answer, the chosen song and links
  with their verification flags, the explanation, the need summary, `trace_url`, and
  `feedback` (`{score, comment, synced_to_langsmith}` or `null`).
  - Pending, waiting and failed requests are left out.
  - `trace_url` points to the run that produced the recommendation (the resumed run after a
    clarification).
- **Errors** use the existing shape and codes. The endpoints raise:
  - `not_found` (404): unknown id;
  - `conflict` (409): answering a request that is not waiting, or rating one that is not
    completed;
  - `validation_error` (422);
  - from the graph: `llm_unavailable`, `llm_invalid_output`, `catalog_unavailable`.

### Feedback: one rating per recommendation

- **Rating again replaces the earlier rating** (score and comment), so a user who changes
  their mind does not leave two contradicting ratings. Enforced by the database:
  - migration `0002_one_feedback_per_recommendation`: the index on `feedback.recommendation_id`
    becomes unique;
  - before creating the index, the migration deletes older duplicate ratings (none exist yet);
  - `FeedbackRepository.save()` is an SQLite upsert.
- **Flow:** save locally with `synced_to_langsmith=false` → send to LangSmith → on success,
  `mark_synced()`. The flag therefore means "LangSmith has the current values". The endpoint
  returns `204` in both cases.
- **LangSmith** — `Tracing.send_feedback()`:
  - key `user_rating`, score 1/0, comment;
  - `run_id` = the run that produced the recommendation:
    `root_run_id(id, resumed=<clarification answered>)` (ADR-04);
  - `session_id` = the project id (needed for run-level feedback in this SDK version);
  - **feedback id `uuid5(namespace, request_id)`**, stable per recommendation. The first rating
    creates it; a later rating, or a create that fails because it already exists, updates it.
    LangSmith therefore holds one current rating per run, like the database.
  - The call is synchronous (sent without `trace_id`, so not batched in the background). This
    makes the `synced` flag reliable. It runs in a worker thread, with `stop_after_attempt=2`
    to keep the request short.
  - Tracing off, or any LangSmith error → `False`, logged; the rating stays unsynced. There is
    no background retry (see Consequences).

### Other changes

- `RecommendationRunner.answer()` checks the checkpoint before resuming. If the paused state
  is gone (e.g. `checkpoints.db` deleted), the row is marked `failed` with `conflict` and the
  API returns 409, instead of running the graph on empty state.
- `RecommendationRepository.list_completed(limit, offset)`: the page, with the feedback loaded
  (`selectinload`), plus the total count.
- The `Recommendation.feedback` relationship is now one-to-one (`Feedback | None`).
- Dependencies in `app/api/deps.py`: `RunnerDep`, `TracingDep`, `RecommendationRepoDep`,
  `FeedbackRepoDep`. The lifespan exposes `app.state.tracing`.
- `docs/implementation-plan.md` (2.6) lists the full set of error codes, including
  `llm_invalid_output` and `conflict`; the frontend (step 7) needs it.

### Tests (262 in total, 24 new)

- `tests/langsmith_fakes.py`: the `RecordingClient` from `test_tracing.py`, moved here and
  extended. It records `create_feedback`/`update_feedback`, and can be made to fail.
- `test_recommendations_api.py` (23): the real app with its routers and lifespan; the runner
  swapped for one with fake LLMs and a fake catalog (`make_harness`).
  - Completed response; clarification round trip (question, answer trimmed, same id,
    completed row); text trimmed before reaching the prompt.
  - 6 invalid request bodies (no LLM call made); LLM failure → 503 with the error shape.
  - Clarification errors (404, 409, 422); resume without a checkpoint → 409 and `failed`.
  - History: paging, total, newest first, waiting requests excluded; limit/offset validation;
    trace links.
  - Feedback:
    - stored and sent (run id, key, score, comment, stable feedback id, project id);
    - rating again → one row, LangSmith updated after a create conflict;
    - LangSmith failing → stored unsynced; tracing off → unsynced;
    - a clarified recommendation → the resumed run;
    - errors (404, 409, 422).
- `test_db.py` (+1): a second rating row for the same recommendation violates the unique index.
- `test_system_api.py`: the expected schema version is now `0002`.

## Deviations from the plan

| Plan | Actual | Reason |
|------|--------|--------|
| `feedback` table without a cardinality rule | One rating per recommendation (unique index, upsert; stable LangSmith feedback id) | Rating again should change the rating, not add a contradicting one, both locally and in LangSmith. |
| Error codes of 2.6 | `conflict` (409) used by both endpoints | See ADR-04. |
| History "list" | Completed recommendations only | The UI shows songs and their ratings; unfinished requests have neither. |

## Issues encountered and how they were solved

1. **The existing test pinned the schema version** (`0001`); updated to `0002`.
2. **Reading the database from synchronous API tests.** The engine belongs to the TestClient's
   event loop, so queries made from the test thread fail. The tests run them through the
   TestClient's `BlockingPortal`.
3. **`create_feedback` has two modes.** With `trace_id` it queues the feedback for background
   upload, so failures go unnoticed. Without it, it posts synchronously, with up to 10 retries
   by default. Decision: no `trace_id`, 2 attempts (see above).
4. **Migration autogenerated against the developer's `.env` data directory** by default
   (`env.py` falls back to `Settings`). It was generated with `DATA_DIR` pointing to a
   temporary directory, so the developer's `data/app.db` was not touched. Checked with
   `alembic upgrade head`, `alembic check` ("No new upgrade operations detected"),
   `downgrade 0001` and `upgrade` again.

## Live verification

Uvicorn ran with the developer's `.env` and `DATA_DIR` in a temporary directory; the API was
called with curl:

| Call | Result |
|------|--------|
| `POST /api/recommendations` (EN, energizing) | 200 `completed` in 13.2 s: Lizzo - Good as Hell, Spotify + YouTube verified, trace link |
| `POST …/feedback` `up`, then `down` + comment | 204, 204 |
| `POST /api/recommendations` (PL, "hmm") | `needs_clarification`: "Jak się teraz czujesz i co ma Ci dać piosenka?" |
| `POST …/clarification` (Polish answer) | `completed`: Brian Eno - 1/1 - Edit, verified; Polish explanation |
| `POST …/feedback` `up` + Polish comment | 204 |
| `POST …/clarification` again | 409 `conflict` |
| `GET /api/recommendations?limit=5` | `total: 2`, newest first, both with feedback `synced_to_langsmith: true` and trace links |
| LangSmith API: `list_feedback` for both runs | one `user_rating` per run; the first holds the **updated** score 0 and comment; the second is on the **resumed** run; both ids equal `feedback_id(request_id)` |

Observation: for "1/1" the Spotify search (market PL) returned the radio edit as the best
match. "Edit" is a variant marker, so it matches; whether to prefer full versions belongs with
the eval work of step 10.

## Consequences

- The frontend (step 7):
  - uses these endpoints and maps every error code in 2.6 to a localized message;
  - sends a rating again to change it;
  - can show "not synced" only if useful (`feedback.synced_to_langsmith`).
- **Unsynced ratings are not retried automatically.** Rating again retries. A periodic sync
  can be added later if LangSmith outages turn out to matter.
- Each long request (one recommendation, 10–40 s) holds an HTTP connection. That is fine for
  one local user; nginx (step 9) needs a proxy read timeout above the worst case, e.g. 120 s.

## Verification

| Command / check | Result |
|-----------------|--------|
| `uv run pytest -q` | 262 passed, no warnings |
| `uv run ruff check .` / `ruff format --check .` | clean |
| `uv run mypy` (strict) | no issues in 75 source files |
| `alembic upgrade head` / `alembic check` / `downgrade 0001` / `upgrade head` (temporary DB) | all succeed; no drift |
| Live API with real keys | see above |
