# ADR-11.4: Step 11 — Usage statistics command

- Status: Accepted
- Date: 2026-10-12
- Step: 11 (additional ADR #4)
- Amends: [ADR-11.3](step-11.3-dark-theme-and-release-script.md) (`scripts/public.sh` gets a
  `stats` command)

## Context

With the app public, the developer wants a quick view of how many and what kind of requests
come in, without opening LangSmith or the OpenAI dashboard. The host has no `sqlite3` CLI, and a
query pasted into the terminal each time is error-prone.

## Decision / What was implemented

`scripts/public.sh stats` runs a Python snippet inside the running backend container
(`docker compose exec -T backend python -`), which has Python, the app's settings and the
database at `/data/app.db`. It opens the database read-only (`file:…?mode=ro`) and prints:

- per UTC day for the last 7 days: recommendations, completed, failed, waiting for an answer
  to the clarifying question, voice input, transcriptions (from the all-visitors counter of
  ADR-11.2) and distinct visitors;
- today's totals of all visitors against `DAILY_TOTAL_RECOMMENDATION_LIMIT` and
  `DAILY_TOTAL_TRANSCRIPTION_LIMIT`, read from the app's own settings, so they match what the
  backend enforces;
- error codes and thumbs up/down of the last 7 days;
- the LangSmith project to open for texts, traces and costs.

Only rows with a visitor are counted: recommendations from before ADR-11.1 belong to no
visitor and are the developer's own local tests.

The command fails with a clear message when Docker or the backend is not running.
`docs/deployment.md` lists it under monitoring, next to the live nginx log
(`docker compose logs -f frontend | grep -v Wget`, without the healthcheck lines).

## Deviations from the plan

None; the guide named the OpenAI Usage page and LangSmith, which stay the places for costs and
request texts.

## Issues encountered and how they were solved

- **No `sqlite3` on the host.** Running the query in the backend container avoids installing
  anything and reuses the app's settings for the limits.
- **Not disturbing the running app.** The database is in WAL mode (ADR-01), so a reader never
  blocks the backend's writes; the connection is read-only and the query takes milliseconds.
- **Days with transcriptions but no recommendation** are not listed (the days come from the
  recommendations); today's transcription total is always shown below the table.

## Consequences

- `scripts/public.sh stats` is the quick check; request texts stay in LangSmith only, and the
  output shows no visitor ids, IPs or texts, so it can be shared.

## Verification

```bash
bash -n scripts/public.sh
scripts/public.sh stats    # on the live deployment: 1 recommendation today, 1/100, 0/200,
                           # no errors, 1 up
```
