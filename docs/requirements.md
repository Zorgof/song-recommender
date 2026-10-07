# Song Recommender — Requirements

Status: **approved draft** · Last updated: 2026-10-07

This document consolidates the original project notes, the gaps found during the
requirements review, and the decisions taken to close them. All decisions below
are confirmed by the developer unless they are marked **[ASSUMPTION]**.

---

## 1. Product summary

A locally hosted web app powered by LLM agents. The user describes their mood and
how their day looks (by text or by voice). The system understands the need and
recommends **one song**: a **Spotify link** with a player embedded in the page, a
**YouTube link**, and a short explanation of why the song fits. The explanation
is in the interface language the user has chosen.

Every step, from user input through the agents' reasoning to the final song choice,
is traced in **LangSmith**. The goal is to understand how the selection is made
first, and to tune it later.

---

## 2. Functional requirements

### 2.1 Input and interface

| ID | Requirement | Source |
|----|-------------|--------|
| FR-1 | User can describe mood and day as free text. | Original |
| FR-2 | User can record the description by voice in the browser. The audio is transcribed to text. | Original |
| FR-3 | After voice input, the transcript is shown and can be edited before it is submitted. | Gap → added |
| FR-4 | The interface is available in **two languages: Polish and English**. A language switcher is visible. The choice is remembered in the browser; on first visit the default follows the browser language, with English as the fallback. | Decided |
| FR-5 | User input is accepted in any language, regardless of the chosen interface language. Speech language is auto-detected. | Decided |
| FR-6 | Input limits: text 3–2000 characters; voice recording at most 90 s or 10 MB. | **[ASSUMPTION]** |

### 2.2 Multi-agent recommendation

| ID | Requirement | Source |
|----|-------------|--------|
| FR-10 | **Agent 1, the Need Analyst**, turns the user's description into a structured *Need Profile*: mood, energy, valence, day context, the goal of the music (match, uplift, calm, focus…), musical hints and things to avoid. It also writes an explicit rationale. | Original |
| FR-11 | **Agent 2, the Music Curator**, proposes ranked song candidates for the Need Profile and gives a rationale for each one. | Original |
| FR-12 | If the description is too vague, Agent 1 may ask **at most one** clarifying question, in the interface language. The user answers it and the flow resumes. | Decided |
| FR-13 | Candidates are **verified against real catalogs** (Spotify Search API, YouTube Data API) before they are returned. A candidate that cannot be verified is rejected, and the curator is asked again with feedback (bounded retries). | Decided |
| FR-14 | The system returns exactly **one** song: title, artist, Spotify link, YouTube link, album art and a "why this song" explanation. | Original + decided |
| FR-15 | The explanation and the need summary shown to the user are written in the **interface language** chosen by the user. | Decided |
| FR-16 | The system avoids recommending songs that appeared in the last *N* recommendations (default N = 50). | Decided |
| FR-17 | Graceful degradation. If Spotify or YouTube cannot be reached, or the YouTube quota is used up, the result falls back to a search URL for that platform. The link is clearly marked **unverified** in the UI. | Decided |
| FR-18 | The result page embeds the **Spotify player** (embed iframe), so the song can be played in the page. | Decided |

### 2.3 Model layer

| ID | Requirement | Source |
|----|-------------|--------|
| FR-20 | Model-agnostic: OpenAI, Anthropic and Google Gemini are supported through configuration only, with no code changes. | Original |
| FR-21 | **The default configuration uses OpenAI** for both tiers, because an OpenAI key is the one currently available. | Decided |
| FR-22 | Two model tiers: **light** and **heavy**. Each tier is configured as `provider:model`, and tiers may use different providers. | Original + decided |
| FR-23 | **Hybrid routing.** Every task has a default tier. A complexity router (heuristics plus a light-model classifier) moves ambiguous or contradictory requests to the heavy tier. Failures escalate to heavy: an invalid structured output, or no verified candidates. | Decided |
| FR-24 | Optional provider fallback chain: if the primary provider of a tier fails, the next configured provider is tried. | **[ASSUMPTION]** |
| FR-25 | At startup, the configuration is validated: the providers needed by the configured tiers must have API keys. | Added |

### 2.4 Speech-to-text

| ID | Requirement | Source |
|----|-------------|--------|
| FR-30 | STT is behind a pluggable interface (`STTProvider`). | Decided |
| FR-31 | The MVP implementation is **OpenAI transcription** (cloud). It uses the same `OPENAI_API_KEY`. There is no local Whisper container. | Decided |
| FR-32 | If no STT provider is configured, the UI hides the microphone button and text input still works. | Added |

### 2.5 Observability and tuning

| ID | Requirement | Source |
|----|-------------|--------|
| FR-40 | Every recommendation is one LangSmith trace. It contains the **verbatim user input** (and the transcript for voice), the clarification question and answer, the routing decision, and every agent call with its **full rendered prompt** (system and user messages), raw output and rationale. It also contains the catalog lookups and the final choice. | Original + decided |
| FR-41 | Traces carry metadata: input mode, interface locale, models and tiers used, provider, prompt versions, app version. Traces can then be filtered and compared in LangSmith. | Added |
| FR-42 | Prompts are versioned files in the repository. The prompt version is recorded on every trace. | Added |
| FR-43 | User feedback (👍/👎 plus an optional comment) is attached to the trace as LangSmith feedback. | Decided |
| FR-44 | The original request and the clarification answer are grouped as one LangSmith thread. | Added |
| FR-45 | An evaluation dataset and an eval script exist, so that future tuning can be measured. | Added |
| FR-46 | LangSmith uses the **US region** endpoint. | Decided |

### 2.6 History

| ID | Requirement | Source |
|----|-------------|--------|
| FR-50 | Recommendations are stored in SQLite: input, locale, Need Profile, chosen track, links and their verification status, models used, trace id, feedback. | Decided |
| FR-51 | The UI has a history view of past recommendations, with their feedback. | Decided |

### 2.7 Deployment and documentation

| ID | Requirement | Source |
|----|-------------|--------|
| FR-60 | The whole app runs with `docker compose up` on a local machine. | Original |
| FR-61 | All configuration goes through a `.env` file. `.env.example` is committed and documented. | Added |
| FR-62 | Code, comments and documentation are in English. The UI has PL and EN translations. | Original + decided |
| FR-63 | The documentation covers the product description, the tech stack, the architecture, the agent flow, routing, configuration, LangSmith usage and the tuning workflow, local setup, and troubleshooting. | Original |

---

## 3. Non-functional requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | **Single user, local hosting, no authentication.** |
| NFR-2 | API keys live only in the backend. They are never sent to the browser and never logged. |
| NFR-3 | Target latency: under 15 s end to end for a text request in the typical case. |
| NFR-4 | The browser only allows the microphone in a *secure context*. `http://localhost` works. Access from another device on the LAN needs HTTPS (a documented reverse-proxy option). |
| NFR-5 | Privacy: user input is sent to OpenAI (LLM and audio transcription) and to LangSmith (US cloud). This is documented. Audio is never sent to LangSmith, only transcripts. |
| NFR-6 | The backend and the agent graph are testable without network access (fake LLMs, mocked HTTP). |
| NFR-7 | Reproducible builds: locked dependencies (`uv.lock`, `package-lock.json`) and pinned base images. |

---

## 4. Out of scope for MVP (future work)

- Full Spotify playback control (OAuth plus the Web Playback SDK) and autoplay. The MVP has the embedded player.
- A local Whisper STT container. The `STTProvider` interface makes it a drop-in addition.
- User music preferences (favourite genres, languages, explicit filter).
- Streaming agent progress to the UI (SSE).
- Multi-user support, authentication, public deployment.
- More than one song per request, or playlists.
- Wellbeing or distress detection: explicitly **not** wanted.

---

## 5. Prerequisites (accounts and keys)

| What | Needed for | Status / notes |
|------|-----------|----------------|
| OpenAI API key | LLM agents (both tiers) and STT | Available. |
| Anthropic or Gemini API key | Alternative providers | Optional; not needed for the MVP. |
| Spotify developer app (Client ID and Secret) | Track verification, links, embed | The owner has **Spotify Premium**, which Development Mode apps require since Feb 2026. Search returns at most 10 results per request. |
| Google Cloud API key with YouTube Data API v3 enabled | YouTube links | Free, 10,000 units per day; one search costs 100 units, so about 100 searches a day. Results are cached. |
| LangSmith account and API key (US region) | Tracing, feedback, evals | The app also runs with tracing switched off. |
| Docker with Compose v2 | Hosting | |

---

## 6. Resolved decisions log

| Topic | Decision |
|-------|----------|
| Song verification | Spotify Search API and YouTube Data API; unverified fallback links |
| STT | OpenAI transcription behind a pluggable interface; no local Whisper |
| Routing | Hybrid: default tier per task, plus a complexity router, plus escalation |
| MVP extras | Feedback to LangSmith, history with no repeats, one clarifying question |
| LLM provider at start | OpenAI (the architecture stays model-agnostic) |
| Users | Single user, no login |
| UI languages | Polish and English; the explanation follows the UI language |
| Spotify | Premium available; embedded player in the page |
| LangSmith region | US |
