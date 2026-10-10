# ADR-04.1: Step 4 — Three curator candidates per attempt instead of five

- Status: Accepted
- Date: 2026-10-10
- Step: 4 (additional ADR #1)
- Amends: [ADR-04](step-04-agent-graph.md) (`CANDIDATE_COUNT`; latency finding)

## Context

The live run of step 4 took 21 s for a simple English request, over the NFR-3 target of 15 s.
The curator call dominated it (13.9 s on the light tier; 1300 completion tokens, 665 of them
reasoning), because it writes a rationale, fit notes and a user-facing explanation for each of
5 candidates. ADR-04 listed options; the developer chose to ask for **3 candidates instead of 5**.

## Decision / What was implemented

- `CANDIDATE_COUNT = 3` in `app/agents/state.py`. The curator prompt receives it through the
  `{{candidate_count}}` placeholder ("Propose exactly 3 different songs"). The prompt file
  `curator.v1.md` is unchanged, so its version stays `v1`.
- Because the rendered prompt now differs under the same prompt version, the root run's
  metadata records **`candidate_count`**. Traces from before and after the change stay
  distinguishable in LangSmith and in the evals of step 10.
- The schema still accepts 1–10 candidates; the number is only asked for, not enforced.
- `docs/implementation-plan.md` (node table, `music_curator`) now says 3 ranked candidates.

## Deviations from the plan

| Plan | Actual | Reason |
|------|--------|--------|
| 5 ranked candidates per curator attempt | 3 | Latency (NFR-3); the developer's decision |

## Issues encountered and how they were solved

None.

## Consequences

- **Fewer fallbacks per attempt.** If none of 3 songs is verified, the next attempt runs on
  heavy, which is slower. Step 10's evals should track the verification success rate and the
  retry rate: if retries become frequent, the gain is lost.
- The heavy path was not measured after the change. From the earlier per-token speed of
  `gpt-6.1-sol` it should drop from about 37 s to the high teens, still over 15 s. Complex
  requests remain the slow case; SSE progress (future work) would help there.
- The curator prompt asks to vary the candidates (artists, eras, styles), which matters more
  with only 3.

## Verification

| Command / check | Result |
|-----------------|--------|
| `uv run pytest -q` | 238 passed; graph test asserts "Propose exactly 3 different songs", tracing test asserts `candidate_count == 3` |
| `uv run ruff check .` / `uv run mypy` | clean / no issues |
| Live: the same simple EN request as in ADR-04, twice | see below |

| Run | Total | Curator (light) | Curator completion tokens (reasoning) | Result |
|-----|-------|-----------------|---------------------------------------|--------|
| ADR-04, 5 candidates | 21.0 s | 13.9 s | 1300 (665) | Brian Eno - An Ending (Ascent) |
| 3 candidates, run 1 | 12.9 s | 7.1 s | 600 (266) | Marconi Union - Weightless; verified |
| 3 candidates, run 2 | 11.3 s | 7.6 s | 675 (362) | Brian Eno - An Ending (Ascent) - Remastered 2005; verified |

The simple path is now under the 15 s target. Run 2 also confirms
[ADR-03.1](step-03.1-prefer-artists-own-recording.md) live: the artist's own (remastered)
recording was chosen, not the collaboration.
