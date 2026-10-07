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
