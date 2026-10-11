# Architecture Decision Records

An ADR is written after every implementation step of the
[implementation plan](../implementation-plan.md). Each ADR records what was **actually**
implemented, the decisions taken (including deviations from the plan), and the issues met
and how they were solved.

## Numbering convention

The ADR number **is** the implementation step number, so it is always clear which step an
ADR belongs to.

| Kind | ID | File name | Example |
|------|----|-----------|---------|
| **Step ADR**: exactly one per implementation step, written when the step is finished | `ADR-NN` (NN = step number, two digits) | `step-NN-<slug>.md` | `ADR-04` → `step-04-agent-graph.md` |
| **Additional ADR**: any further decision, amendment or fix that belongs to a step | `ADR-NN.M` (M = 1, 2, 3 … within that step) | `step-NN.M-<slug>.md` | `ADR-04.2` → `step-04.2-switch-checkpointer.md` |

Rules:

1. A step ADR always has the plain step number. Additional ADRs never shift or reuse it.
2. An additional ADR is numbered under the step **whose scope it changes**. If a decision is cross-cutting and changes no single step, it is numbered under the **most recently finished step** at the time it is made.
3. Numbers are never reused or renumbered. A decision that is replaced keeps its number and gets the status `Superseded by ADR-XX(.Y)`.
4. When an additional ADR amends an earlier ADR, both link to each other: the new one with an `Amends:` line, and the old one in its `Status:` line.
5. File names sort in the right order: `step-00-…`, `step-00.1-…`, `step-00.2-…`, `step-01-…`.

## Index

### Step 0 — Scaffolding

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-00](step-00-scaffolding.md) | Repository scaffolding | Accepted (amended by ADR-00.1) |
| [ADR-00.1](step-00.1-python-3-14-and-dev-environment.md) | Python 3.14.8 and development environment setup | Accepted |

### Step 1 — Backend foundation

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-01](step-01-backend-foundation.md) | Backend foundation: config, logging, errors, health/meta, SQLite + Alembic | Accepted (amended by ADR-01.2) |
| [ADR-01.2](step-01.2-langsmith-workspace-id.md) | LangSmith workspace id for organization-scoped service keys | Accepted |

### Step 2 — LLM layer and routing

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-02](step-02-llm-layer-and-routing.md) | Model registry, structured calls with escalation, routing heuristics | Accepted (amended by ADR-02.1) |
| [ADR-02.1](step-02.1-anthropic-structured-output.md) | Native structured output for Anthropic models | Accepted |

### Step 3 — Music catalog clients

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-03](step-03-music-catalog-clients.md) | Spotify and YouTube clients, fuzzy matching, track link cache | Accepted (amended by ADR-03.1) |
| [ADR-03.1](step-03.1-prefer-artists-own-recording.md) | Prefer the artist's own recording when matches tie | Accepted |

### Step 4 — Agent graph

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-04](step-04-agent-graph.md) | LangGraph agents, clarification interrupt, persistence, LangSmith root runs | Accepted (amended by ADR-04.1) |
| [ADR-04.1](step-04.1-three-candidates.md) | Three curator candidates per attempt instead of five | Accepted |

### Step 5 — Recommendation API and history

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-05](step-05-recommendation-api.md) | Recommendation, clarification, history and feedback endpoints | Accepted |

### Step 6 — Speech-to-text (OpenAI)

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-06](step-06-speech-to-text.md) | STTProvider, OpenAI transcription (`gpt-transcribe`), transcription endpoint | Accepted |

### Step 7 — Frontend: text flow and i18n

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-07](step-07-frontend-text-flow-and-i18n.md) | React app: text flow, result card, feedback, history, PL/EN i18n | Accepted |

### Step 8 — Frontend: voice flow

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-08](step-08-frontend-voice-flow.md) | Voice recording, transcript review, STT-aware microphone | Accepted |

### Step 9 — Docker

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-09](step-09-docker.md) | Docker images, nginx, Compose (prod + dev), data volume ownership | Accepted |

### Step 10 — Evals and tuning groundwork

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-10](step-10-evals.md) | LangSmith dataset, eval target, metrics, aspect-based LLM judge, baseline | Accepted |

### Step 11 — Documentation

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-11](step-11-documentation.md) | README, architecture, configuration, tuning and troubleshooting docs, screenshots | Accepted |

## Templates

Step ADR:

```markdown
# ADR-NN: Step N — <title>

- Status: Proposed | Accepted | Superseded by ADR-XX(.Y)
- Date: YYYY-MM-DD
- Step: N

## Context
Why this step exists and what it had to deliver.

## Decision / What was implemented
The concrete result: files, tools, versions, configuration.

## Deviations from the plan
What differs from docs/implementation-plan.md, and why.

## Issues encountered and how they were solved

## Consequences
What this enables or constrains for later steps; open follow-ups.

## Verification
Commands run and their results.
```

Additional ADR: the same sections, with this header instead:

```markdown
# ADR-NN.M: Step N — <title>

- Status: Proposed | Accepted | Superseded by ADR-XX(.Y)
- Date: YYYY-MM-DD
- Step: N (additional ADR #M)
- Amends: [ADR-NN](step-NN-<slug>.md) (what exactly), if it amends an earlier ADR
```
