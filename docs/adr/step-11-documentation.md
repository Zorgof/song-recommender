# ADR-11: Step 11 — Documentation

- Status: Accepted
- Date: 2026-10-11
- Step: 11

## Context

Step 11 of the [implementation plan](../implementation-plan.md) completes the documentation
(FR-63):
- `README.md`: what the app is, quick start, prerequisites, how to switch to Anthropic or
  Gemini, screenshots;
- `docs/architecture.md`, `docs/configuration.md`, `docs/observability-and-tuning.md` and
  `docs/troubleshooting.md`.

"Done when": a fresh clone can be set up using only the README.

## Decision / What was implemented

### Documents

| File | Contents |
|------|----------|
| `README.md` (rewritten) | what the app does, 4 screenshots, how it works in 4 steps, quick start with a table of the four services (what each key is for, where to get it, what happens without it), the minimal `.env` edits, provider switching (Anthropic, Gemini, mixed with fallback), a documentation index, development commands, tech stack, layout, privacy |
| `docs/architecture.md` | system diagram, end-to-end sequence diagram (including clarification), agent graph diagram and node table, routing rules and tier policy, escalation and fallback table, language handling, persistence, REST API and error codes, frontend states, repository layout |
| `docs/configuration.md` | every variable (application, LLM tiers and keys, STT, catalogs, LangSmith, dev/Docker-only ones) with default and meaning; provider examples; how to get Spotify and YouTube credentials; which values Docker Compose overrides |
| `docs/observability-and-tuning.md` | trace structure, every metadata key and tag, clarification threads, `user_rating` feedback, the eval CLI and its options, metrics with the baseline values, comparing experiments, the prompt-change workflow, other tuning levers |
| `docs/troubleshooting.md` | starting the app, recommendations, voice input, evaluation and development problems, each with the log message to look for and the fix |
| `docs/images/*.png` | screenshots: input (EN), result with the Spotify player (EN), clarifying question (PL), history (PL) |

- The facts were taken from the code, not from the plan: routing thresholds, escalation rules,
  log messages, metadata keys, defaults, error codes.
- Each troubleshooting entry comes from behaviour seen during steps 1–10: the "not writable"
  message, the YouTube quota log, LangSmith 403, the nginx 120 s limit, the secure-context
  rule.
- Cross-document links and anchors were checked with a script. The only unresolved link is the
  intentional `step-NN-<slug>.md` placeholder in the ADR template.
- `.env.example` now shows concrete Anthropic and Gemini model ids instead of placeholders.

### Provider examples

| Provider | Light | Heavy | Source |
|----------|-------|-------|--------|
| Anthropic | `claude-haiku-5-5` | `claude-sonnet-5-5` | current Claude model family |
| Gemini | `gemini-3.5-flash-lite` | `gemini-3.8-flash` | Google's model list: "For any new projects, use our latest models: 3.5 Flash-Lite or 3.8 Flash" ([ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models)) |

All three documented configurations (Anthropic, Gemini, mixed with fallback) were built offline
with the real `ModelRegistry`, with `LLM_HEAVY_REASONING=on`. A missing key gives the expected
startup message.

### Screenshots

- Taken from the running Docker stack with headless Chromium. It ran in the
  `mcr.microsoft.com/playwright/python:v1.63.0-noble` image, attached to the compose network.
- `playwright==1.63.0` was installed with `pip --target` inside the throw-away container,
  because the image has no Python package and no `venv`. The script was removed after use, and
  the image (3.5 GB) was deleted afterwards.
- Two real recommendations were made for them (EN result; the PL "hmm" got a clarifying
  question).

## Deviations from the plan

- **ADR-02.1, a code fix inside a documentation step.** Building the Anthropic example showed
  that `claude-sonnet-5-5` and `claude-opus-5-5` do not support LangChain's default
  structured-output method (forced tool calls). The documented example would have been
  unreliable, so `ModelRegistry` now uses Claude's native JSON-schema output for Anthropic.
  Details and tests are in [ADR-02.1](step-02.1-anthropic-structured-output.md).
- **A small UI fix** in `frontend/src/index.css`: `.btn-primary` and `.btn-secondary` got
  `gap-1.5` (see Issues).

## Issues encountered and how they were solved

1. **Anthropic structured output.** See ADR-02.1. The change is verified offline only; no
   Anthropic key is available.
2. **Current Gemini ids.** A web search returned conflicting third-party lists, so the ids were
   taken from Google's own model page.
3. **No microphone button in the headless browser.** Chromium's headless shell ignores
   `--unsafely-treat-insecure-origin-as-secure`. `isSecureContext` was `false` there and
   `navigator.mediaDevices` was missing, so the app correctly hid the microphone. Full
   Chromium (`channel="chromium"`) honours the flag. The probe also confirmed the app's
   secure-context logic.
4. **"🎤Record" without a space.** The screenshot showed the icon stuck to the text. The JSX
   has the space, but the button is `inline-flex`, and a whitespace-only text node between
   flex items is not rendered. The 👍/👎 buttons are not flex and were fine. `gap-1.5` on the
   button classes fixes it; the screenshot was retaken.
5. **A mistake caught by the link check:** a troubleshooting anchor in `configuration.md` was
   shorter than GitHub's generated id. It was fixed.
6. **A wrong statement corrected before publishing:** the configuration page first said that
   `LANGSMITH_*` shell variables do not affect the app. They do, because they are settings
   fields. The text now says that other tracing variables (`LANGCHAIN_TRACING_V2`, …) are the
   ones ignored.

## Fresh-clone verification ("done when")

The repository's tracked and new files were copied to an empty temporary directory, and the
README's steps were followed literally:
- `cp .env.example .env`;
- only the keys the README lists were filled in (OpenAI, Spotify id and secret, YouTube,
  LangSmith key and workspace id); a diff confirmed that every other line equals
  `.env.example`;
- `APP_PORT=8082` was set, to run beside the main stack;
- `docker compose -p sr-fresh up --build -d`.

| Check | Result |
|-------|--------|
| Containers | backend healthy, then frontend started |
| `GET :8082/` | 200 |
| `GET /api/meta` | `production`; `openai:gpt-6-luna` / `openai:gpt-6.1-sol` from the defaults in `.env.example`; STT, Spotify, YouTube and LangSmith all enabled |
| `POST /api/recommendations` | 200 in 13.3 s: Nils Frahm - Ambre, Spotify and YouTube verified, trace link present |

The temporary project, its images and the directory were removed afterwards.

## Consequences

- The README is the entry point; the four docs cover architecture, every setting, tuning and
  failures. The component READMEs stay as module references.
- **Kept as known limits, now documented:**
  - Anthropic and Gemini are verified offline only;
  - LAN access needs an HTTPS proxy (the Caddy example is not part of the tested setup);
  - the YouTube quota is about 100 searches a day;
  - eval results vary between runs.
- The docs quote baseline eval numbers (ADR-10). Update them when a new baseline is accepted.

## Verification

| Command / check | Result |
|-----------------|--------|
| `cd backend && uv run pytest -q` | 327 passed |
| `uv run ruff check .`, `ruff format --check .`, `uv run mypy` | clean |
| `cd frontend && npm test`, `npm run lint`, `npx prettier --check .`, `npm run build` | 65 passed; clean; clean; succeeds |
| Link and anchor check over 27 Markdown files | no broken links (except the ADR template placeholder) |
| Fresh copy set up with the README only | working app, see above |
| Main stack (`docker compose ps`) | rebuilt with the final code; backend and frontend healthy |
