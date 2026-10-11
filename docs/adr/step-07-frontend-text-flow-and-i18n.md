# ADR-07: Step 7 — Frontend: text flow and i18n

- Status: Accepted
- Date: 2026-10-11
- Step: 7

## Context

Step 7 of the [implementation plan](../implementation-plan.md) builds the React app on top of
the step 0 skeleton (section 2.8). It covers the text flow end to end:
- describe the day;
- answer the clarifying question if one is asked;
- see the song, play it in the Spotify embed, rate it;
- browse the history.

It also adds the PL/EN interface (FR-4, FR-15, FR-17, FR-18, FR-43, FR-51). Voice input is
step 8.

"Done when":
- the full text flow works in both languages against the dev backend;
- the explanation follows the selected language;
- Vitest tests cover the card, the clarification and language switching.

## Decision / What was implemented

### Dependencies (`frontend/package.json`)

| Package | Version | Use |
|---------|---------|-----|
| `@tanstack/react-query` | 5.104 | history query, recommendation / clarification / feedback mutations |
| `react-router` | 8.4 | declarative routes (`BrowserRouter`, `Routes`, `NavLink`, `useSearchParams`) |
| `i18next` / `react-i18next` | 26.4 / 17.0 | translations |
| `tailwindcss` + `@tailwindcss/vite` | 4.3 | styling (Vite plugin, no PostCSS config) |
| dev: `vitest`, `jsdom`, `@testing-library/react`, `user-event`, `jest-dom`, `dom` | 5.0, 30.1, 16.3, 14.6, 7.0, 10.4 | tests |

- `npm install` also updated the already present React, types and Vite to the latest patch
  versions within their ranges: React 19.3, Vite 8.3.3.
- `tsconfig.app.json`:
  - `"strict": true` is now set explicitly;
  - `resolveJsonModule` is on, for the translation files.
- `vite.config.ts` holds the Vitest configuration:
  - `defineConfig` from `vitest/config`;
  - `jsdom`, a setup file, `restoreMocks`, `unstubGlobals`.
- New scripts: `test` (`vitest run`) and `test:watch`.

### Structure (`frontend/src/`)

| Path | Contents |
|------|----------|
| `api/types.ts` | TypeScript mirror of the backend schemas: `Recommendation`, the `completed` / `needs_clarification` union, `HistoryItem`, `HistoryPage`, feedback, requests |
| `api/client.ts` | `fetch` wrapper and `ApiError(code, message, status)`; typed `api.recommend / answerClarification / sendFeedback / history` |
| `api/queries.ts` | `useHistory(offset)` (`keepPreviousData`), `useRecommend`, `useAnswerClarification`, `useSendFeedback`; every mutation invalidates the history |
| `i18n/` | i18next instance, locale detection and storage, `setLocale`, `currentLocale`; `i18next.d.ts` for type-checked keys |
| `locales/en.json`, `pl.json` | Every UI string and every error code |
| `components/` | `Layout` (header, nav, switcher, `document.title`), `LanguageSwitcher`, `MoodInput`, `ThinkingIndicator`, `ClarificationPrompt`, `RecommendationCard`, `FeedbackButtons`, `ErrorMessage` |
| `pages/` | `HomePage` (the flow), `HistoryPage` |
| `lib/` | `formatDateTime` (`Intl`), `errorCode` (code → translation key) |
| `test/` | setup, `renderWithProviders` / `renderApp`, `mockFetch`, fixtures |

### Behaviour

- **Language (FR-4).**
  - The header has a switcher: `EN` and `PL` buttons with `aria-pressed`, each labelled with the
    language's own name.
  - The choice is stored in `localStorage` (`song-recommender.locale`). Reads and writes are in
    try/catch, so blocked storage only means the choice is not kept.
  - On the first visit the language follows `navigator.languages`: the first supported base
    tag, e.g. `de-DE, pl-PL` → `pl`. Otherwise English.
  - `<html lang>` and `document.title` follow the language.
- **Locale of requests (FR-15).** Every recommendation request sends `currentLocale()`. The
  backend writes the question, the need summary and the explanation in that language. Changing
  the language later does not re-translate a result already shown.
- **Home flow.** It is a small state machine: `input → thinking → (clarifying → thinking) →
  result`.
  - An error returns to the input, with the text kept and "Try again" offered.
  - An error after an answer keeps the question, so the user can answer again. After
    `not_found` or `conflict` (the request is gone or no longer waiting), the flow starts over.
  - "Start over" on the question keeps the description; "Describe another moment" clears it.
- **Input (FR-6).** 3–2000 characters after trimming, as in the backend. `maxLength` is set,
  with a counter. A too-short text shows an inline message and is not sent. Ctrl/⌘+Enter
  submits.
- **Result card.**
  - Shows album art, title, artist, the need summary, the explanation, and a "View trace in
    LangSmith" link when `trace_url` is set.
  - The **Spotify embed** (`open.spotify.com/embed/track/{id}`, 152 px, lazy) appears only for a
    verified track (FR-18).
  - Links open in a new tab with `rel="noopener noreferrer"`. A fallback search link is labelled
    "Search on …" and carries an amber **unverified** badge with an explanatory tooltip (FR-17).
  - History uses a compact variant: smaller art, `h3` instead of `h2`, no player. Several
    iframes on one page would be heavy.
- **Feedback (FR-43).**
  - A thumb (👍/👎) is **sent at once**, so a rating is not lost if the user skips the comment.
  - The comment field then appears; "Send" re-sends the score with the comment.
  - Rating again replaces the earlier rating (ADR-05).
  - The history shows the stored rating and lets the user change it. A rating not yet synced
    to LangSmith gets a short note.
- **History (FR-51).**
  - Shows 20 items per page, with the page number in the URL (`?page=2`), so Back and reload
    keep it.
  - Each item shows the date in the UI locale (`Intl.DateTimeFormat`, medium date + short
    time), a "voice" tag, the input text, the clarification Q&A, the compact card and the
    feedback.
  - There is also an empty state and an error state with a retry.
- **Errors.**
  - `errorCode()` maps `ApiError.code` to `errors.<code>` in the locale files. That covers
    every backend code in 2.6, including the STT codes from ADR-06, which step 8 uses.
  - Unknown codes and non-JSON error responses show `internal_error`.
  - An unreachable server raises `ApiError('network_error')`, a client-side code; the plan's
    list of codes now mentions it.
- **Styling.**
  - Tailwind v4, with light and dark themes via `prefers-color-scheme` (`dark:` variants).
  - Three component classes in `index.css` (`.field`, `.btn-primary`, `.btn-secondary`) keep
    the JSX readable.
- **Accessibility.**
  - Labelled form fields; `role="status"` while thinking; `role="alert"` for errors.
  - `aria-pressed` on toggles; visible focus outlines; the answer field is focused when the
    question appears.

### Tests (Vitest + Testing Library, jsdom)

44 tests in 7 files, no network. `fetch` is replaced by `mockFetch`, which records the method,
path and JSON body of each request.

| File | Covers |
|------|--------|
| `components/RecommendationCard.test.tsx` | verified song with player and links; unverified badges and no player; mixed verification; trace link on/off; compact variant; Polish labels |
| `pages/HomePage.test.tsx` | text → result (trimmed body, `locale: en`); progress status; **clarification and resume** (request path and body, focus); start over; too-short text not sent; Ctrl+Enter; localized error, text kept, retry; failed answer keeps the question, `conflict` starts over; "describe another" |
| `components/LanguageSwitcher.test.tsx` | **switching to Polish** (UI texts, `aria-pressed`, storage, `<html lang>`); the request sends `locale: pl` and the Polish explanation is shown; errors in Polish |
| `components/FeedbackButtons.test.tsx` | thumb sent at once, then with the comment; changing a stored rating; "not synced" note; error |
| `pages/HistoryPage.test.tsx` | items with Q&A, voice tag and stored feedback; dates in the UI locale and Polish plural; paging through 3 pages (offsets); page from the URL; empty state; error and retry; navigation |
| `i18n/i18n.test.ts` | EN/PL have the same keys and placeholders; Polish plural forms; detection (stored, browser, fallback, invalid stored value, blocked storage); `setLocale` |
| `api/client.test.ts` | JSON post; 204; id escaping; history query; error shape → `ApiError`; non-JSON error; network error |

A mutation check confirmed the tests catch a regression: with a hard-coded `locale: 'en'` in
`HomePage`, the language test fails.

## Deviations from the plan

- **No `HistoryList` component.** The history entry is a small component in `HistoryPage`,
  and the card is reused in compact form.
- **No locale-detection package.** `i18next-browser-languagedetector` is not used. The rule is
  three lines, and the plan asks for the storage access to be wrapped in try/catch, which is
  simpler to guarantee in own code.
- **Declarative routing** (`BrowserRouter`) instead of a data router. There are two pages and
  data comes from TanStack Query, so route loaders would add nothing.
- **`/api/meta` is not used yet.** Hiding the microphone when STT is disabled (FR-32) belongs
  to step 8, which also adds the meta query.
- **Ratings can be changed in the history.** The plan only says the history shows feedback.
  Reusing `FeedbackButtons` made rating from the history free.

## Issues encountered and how they were solved

1. **Newer major versions than the plan assumed:** React Router 8, Vitest 5, jsdom 30,
   jest-dom 7. Their type definitions were checked before writing code. The APIs used here
   (`BrowserRouter`/`Routes`/`NavLink`/`useSearchParams`, `vitest/config`,
   `@testing-library/jest-dom/vitest`) are unchanged.
2. **Vitest globals are off,** so Testing Library cannot register its automatic `cleanup`.
   `test/setup.ts` calls it in `afterEach`, and also resets the language and `localStorage`
   before each test.
3. **`erasableSyntaxOnly`** (template default) forbids TypeScript parameter properties, so
   `ApiError` declares its fields explicitly.
4. **oxlint `only-export-components`** warned about a helper exported from
   `RecommendationCard.tsx`, which would break Fast Refresh. It is now module-private.
5. **jsdom does not implement `window.scrollTo`** (used when changing history pages). The setup
   stubs it, so test output stays clean.
6. **No browser in the environment** for the manual check. The flow was verified at two levels;
   see Live verification:
   - the exact requests the UI makes were sent through the Vite proxy;
   - a temporary Vitest test rendered the real `App` against the running backend. It was
     deleted after the run.

   In that test, Node's `fetch` (unlike a browser's) does not resolve the relative `/api/…`
   URL against the page, so the temporary test prefixed the origin. The app code is unchanged.
   A click-through in Chrome/Firefox is left to the developer.

## Live verification

The backend ran with the developer's `.env` and a temporary `DATA_DIR`; `vite` dev ran on
`:5173`. All calls went through the Vite proxy, as the browser would send them.

| Check | Result |
|-------|--------|
| `GET :5173/api/health`, `GET :5173/history` (SPA route) | 200 / 200 (index.html) |
| PL description → `POST /api/recommendations` (`locale: pl`) | 200 in 15.9 s: Nick Drake - Pink Moon, both links verified; need summary and explanation in **Polish**; response keys exactly match `Recommendation` in `types.ts` |
| `hmm` with `locale: en` / `pl` | `needs_clarification`, question in English / Polish |
| Answers to both questions | `completed`: Cat Power - Sea of Love (EN explanation), Ólafur Arnalds - saman (PL explanation) |
| Answering the same question again | 409 `conflict` (the UI then starts over) |
| `POST …/feedback` `up` + comment | 204; the history shows `synced_to_langsmith: true` |
| History `limit=2` / `offset=2` | newest first, with clarification Q&A; second page with the stored feedback |
| `https://open.spotify.com/embed/track/<id>` | 200, no `X-Frame-Options` / `frame-ancestors`, so it can be embedded |
| Real `App` in jsdom against the backend (temporary test): switch to PL, type, submit | "Szukam piosenki…" status → card with a Polish explanation (Earth, Wind & Fire - September) → 👍 "Dzięki! Ocena zapisana." → History shows the new item with the synced rating |

## Consequences

- **Step 8 (voice)** plugs into `HomePage`:
  - adds `recording` / `transcribing` / `reviewing` phases and an `api.transcribe`;
  - adds a `useMeta` query to hide the microphone;
  - sends `input_mode: 'voice'` and `transcript`;
  - the error messages for the STT codes already exist.
- **Step 9 (nginx)** must serve `index.html` for unknown paths (`try_files $uri /index.html`),
  so `/history` works on reload; the dev server already does this.
- **Leaving the page during a request loses the result on the Home page.** The recommendation
  still completes on the backend and appears in the history. Keeping a running flow across
  navigation can come later if needed.
- **Bundle:** 364 KB JS (115 KB gzip). Code splitting is not needed for two pages.

## Verification

| Command / check | Result |
|-----------------|--------|
| `npm test` | 44 passed (7 files) |
| `npm run lint` (oxlint) | no findings |
| `npm run build` (`tsc -b` + `vite build`) | succeeds |
| `npm run format:check` | all files formatted |
| Live checks with the dev backend | see above |
