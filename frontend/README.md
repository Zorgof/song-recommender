# Song Recommender — frontend

React + TypeScript single-page app built with Vite. See the [root README](../README.md) and
[docs/implementation-plan.md](../docs/implementation-plan.md).

## Development

Requires Node.js 24 LTS (see `.nvmrc`). Start the backend first (see `backend/README.md`); the
dev server proxies `/api` to `http://localhost:8000`.

```bash
npm install
npm run dev            # dev server on http://localhost:5173
npm run build          # type check + production build into dist/
npm test               # Vitest + React Testing Library (jsdom), no network
npm run test:watch
npm run lint           # oxlint
npm run format         # prettier --write
npm run format:check   # prettier --check
```

## Stack

React 19, TypeScript (strict), Vite, TanStack Query, React Router (declarative routes),
Tailwind CSS v4 (`@tailwindcss/vite`), react-i18next. Tests: Vitest, Testing Library, jsdom.

## Layout

```
src/
  main.tsx              providers: QueryClient, BrowserRouter; loads i18n and styles
  App.tsx               routes: / (HomePage), /history (HistoryPage), inside Layout
  api/                  types.ts (mirrors the backend schemas), client.ts (fetch + ApiError),
                        queries.ts (TanStack Query hooks)
  i18n/                 i18next setup, locale detection and persistence, typed keys
  locales/              en.json, pl.json: every UI string and error message
  components/           Layout, LanguageSwitcher, MoodInput, ThinkingIndicator,
                        ClarificationPrompt, RecommendationCard, FeedbackButtons, ErrorMessage,
                        VoiceRecorder, TranscriptReview
  pages/                HomePage (the recommendation flow), HistoryPage
  lib/                  formatting, error code mapping, audio helpers, useVoiceRecorder
  test/                 test setup, render helpers, fetch mock, fixtures, fake microphone
```

## Behaviour

- **Language (FR-4).** EN/PL switcher in the header. The choice is stored in `localStorage`
  (`song-recommender.locale`; every access is in try/catch). The first visit follows
  `navigator.languages`, falling back to English. `<html lang>` follows the UI language.
- **Locale of requests (FR-15).** Every recommendation request sends the current UI language as
  `locale`; the backend writes the clarifying question, need summary and explanation in it. The
  description itself may be in any language (FR-5).
- **Home flow:** input → thinking → (clarifying question → thinking) → result, or an error with
  the text kept. After a `not_found`/`conflict` error on an answer the flow starts over.
- **Voice input (FR-2, FR-3, step 8):** a 🎤 Record button next to "Find my song", shown only
  when `/api/meta` reports STT enabled (FR-32) and the browser can record. Microphone access
  needs a secure context: `http://localhost` or https (NFR-4); elsewhere a hint explains why
  there is no button.
  - Recording: `MediaRecorder`, webm/opus (Chrome, Firefox), ogg/opus or mp4 (Safari),
    timer, automatic stop at 90 s (FR-6); Cancel discards it. The microphone is released when
    recording ends or the view is left.
  - Stop → `POST /api/transcriptions` → the transcript is shown for editing, with the detected
    language. "Find my song" sends the edited text with `input_mode: "voice"` and the
    original `transcript` (FR-40). "Record again" and "Discard" are available.
  - Blocked or missing microphone, no speech recognized, transcription errors: localized
    messages; a failed transcription can be retried with the same recording.
- **Result card:** album art, title, artist, the Spotify embed (verified tracks only, FR-18),
  Spotify and YouTube links, "unverified" badges on fallback search links (FR-17), the need
  summary, the explanation and a LangSmith trace link when tracing is on.
- **Feedback (FR-43):** a thumb is sent at once; an optional comment is sent with "Send". Rating
  again replaces the earlier rating. Ratings can also be given or changed in the history.
- **History (FR-51):** 20 per page, page number in the URL (`/history?page=2`).
- **Errors:** the backend's `error.code` (and `network_error` for an unreachable server) is
  mapped to a message in `locales/*.json` under `errors.*`; unknown codes show `internal_error`.
- **Translation keys are type-checked** (`i18n/i18next.d.ts`), and a test checks that `en.json`
  and `pl.json` have the same keys and placeholders.
