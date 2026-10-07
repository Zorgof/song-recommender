# ADR-01.2: Step 1 — LangSmith workspace id for organization-scoped service keys

- Status: Accepted
- Date: 2026-10-07
- Step: 1 (additional ADR #2)
- Amends: [ADR-01](step-01-backend-foundation.md) (configuration: new `LANGSMITH_WORKSPACE_ID` setting)

## Context

Before step 2, every external credential in `.env` was checked with a one-off script. The script
was not committed and printed only HTTP status codes; error bodies went through `SecretRedactor`.

| Service | Check | Result |
|---------|-------|--------|
| OpenAI | `GET /v1/models` | 200 |
| Spotify | Client Credentials token + one track search (market `PL`) | 200 / 200, track found |
| YouTube Data API v3 | one `search.list` (type=video, category Music) | 200, video found |
| LangSmith (US) | `GET /api/v1/sessions` | **403 Forbidden** |

Diagnosis of the LangSmith error:
- The key is a **service key** (`lsv2_sk_` prefix). It works against the **US** endpoint: `GET /api/v1/workspaces` returns 200 there and 403 on the EU endpoint.
- Workspace-level operations (listing projects, ingesting runs with `POST /runs`) returned 403.
- The same calls with the header `X-Tenant-Id: <workspace id>` returned 200 for projects and **202 Accepted** for trace ingestion.

Conclusion: the key is scoped to the **organization**, and such keys must name the target workspace on every request.

## Decision / What was implemented

- New optional setting **`LANGSMITH_WORKSPACE_ID`** (`Settings.langsmith_workspace_id`, a string).
  - It is not a secret: it is a workspace UUID, visible in the LangSmith UI.
  - It is documented in `.env.example`: required for organization-scoped service keys (`lsv2_sk_…`), optional for personal access tokens (`lsv2_pt_…`).
- `test_config.py::test_defaults` asserts that it defaults to `None`.
- Step 4 must pass it to the LangSmith client explicitly (`workspace_id=`), together with the API key and endpoint. This adds to the ADR-01 consequence that SDKs do not see values that exist only in `.env`.

## Alternatives considered

- **Create a workspace-scoped service key instead.** Also valid, and it needs no extra setting. It was not chosen as the only fix, because the app should work with either key type. The setting costs one optional variable.

## Issues encountered and how they were solved

- A 403 with a valid key is easy to misread as a wrong region or a revoked key. The diagnosis compared the US and EU endpoints and requests with and without `X-Tenant-Id`, which isolated the cause.
- The diagnosis ingested one test run named `credentials-smoke-test` into the `song-recommender` project. It is harmless and can be deleted in the LangSmith UI.

## Consequences

- Tracing (step 4) works with both key types once `LANGSMITH_WORKSPACE_ID` is set for a service key.
- `docs/configuration.md` (step 11) must explain the two key types and when the workspace id is needed.

## Verification

| Check | Result |
|-------|--------|
| `GET /api/v1/sessions` and `POST /runs` with `X-Tenant-Id` | 200 / 202 |
| `uv run pytest -q` / `ruff` / `mypy` | 44 passed / clean / no issues |
