# ADR-01.1: Step 1 — Secret-scanner-safe test fixtures

- Status: Accepted
- Date: 2026-10-07
- Step: 1 (additional ADR #1)
- Amends: [ADR-01](step-01-backend-foundation.md) (test fixtures of the logging, error and config tests)

## Context

After step 1 was pushed, a secret scanning service sent "Action needed: Secrets detected in
Zorgof/song-recommender" for `backend/tests/test_logging.py`.

What was found:
- The flagged strings were **fake credentials written by hand** for the log-redaction tests. They had the exact shape of real keys:
  - Google (`AIza` + 35 characters);
  - OpenAI (`sk-proj-…`);
  - LangSmith (`lsv2_pt_…`);
  - a JWT-like bearer token.
  Similar strings were in `test_errors.py`, `test_config.py` and `test_system_api.py`.
- **No real secret was ever committed**:
  - the full history was scanned for key patterns, and only these test fixtures matched;
  - `.env` was never tracked;
  - none of the values in the local `.env` appears in any commit.
- Scanners match the *shape* of a key, not whether it is valid, so these fakes are indistinguishable from real leaks.

## Decision / What was implemented

- New `backend/tests/fakes.py` assembles fake credentials **at runtime**, e.g. `"AI" + "za" + "x" * 35`. No literal in the repository has the shape of a key.
  - Exports: `FAKE_OPENAI_KEY`, `FAKE_LANGSMITH_KEY`, `FAKE_GOOGLE_KEY`, `FAKE_BEARER_TOKEN`, and `fake_key(prefix, length)`.
- Tests that need a key-*shaped* value, to check the redaction patterns, use these constants: `test_logging.py`, `test_errors.py`.
- Tests that only need *some* secret value use plain `test-…` strings: `test_config.py`, `test_system_api.py`.
- **Rule for the code base:** never write a literal key-shaped string (`sk-…`, `lsv2_…`, `AIza…`, JWTs, `ghp_…`, …) into code, tests, docs or fixtures. Use `tests/fakes.py`.
- The fix replaces the step 1 commit. The history is rewritten (amend + force push), so the key-shaped strings are no longer reachable from any branch.

## Issues encountered and how they were solved

1. **The automated history rewrite was blocked.** Claude Code's safety classifier denied `git commit --amend`, and the project rule in `CLAUDE.md` makes the developer responsible for commits anyway. The amend and the force push are run by the developer.
2. **GitHub keeps unreachable commits for a while.** After the force push, the old commit is no longer on any branch, but it may still be readable by its SHA until GitHub garbage-collects it. Only real secrets justify asking GitHub Support to purge it. Here the values were fake, so closing the scanner alert as a false positive (test credential) is enough.

## Consequences

- No key rotation is needed: none of the flagged values was a real credential.
- Every future test that needs credentials uses `tests/fakes.py`.

## Verification

| Check | Result |
|-------|--------|
| History scan (all commits) for `sk-`, `lsv2_`, `AIza`, `ghp_`, private keys, `*_KEY=`/`*SECRET=` assignments | Only the test fixtures of the step 1 commit |
| Local `.env` values (≥ 8 characters) searched in every commit and commit message | 0 hits |
| Working tree scan for key-shaped literals after the fix | None |
| `uv run pytest -q` / `ruff check` / `mypy` | 44 passed / all checks passed / no issues |
