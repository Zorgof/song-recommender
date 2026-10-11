# ADR-08: Step 8 — Frontend: voice flow

- Status: Accepted
- Date: 2026-10-11
- Step: 8

## Context

Step 8 of the [implementation plan](../implementation-plan.md) adds voice input to the React
app (FR-2, FR-3, FR-6, FR-32, NFR-4; section 2.8). The flow is:
- record in the browser;
- send the clip to `POST /api/transcriptions` (ADR-06);
- show the transcript for editing;
- send the edited text as a voice request.

The microphone is hidden when STT is disabled.

"Done when": voice → transcript → edit → recommendation works in Chrome and Firefox on
`localhost`.

## Decision / What was implemented

### API layer

- `api.meta()` and `useMeta()`: the query uses `staleTime: Infinity`, because the configuration
  only changes when the backend restarts.
- `api.transcribe(blob, filename)` and `useTranscribe()`: a multipart upload in the field
  `audio`. The browser sets the boundary.
- New types: `Meta`, `Transcription`. `RecommendationRequest.transcript` already existed
  (ADR-07).

### Recording — `lib/audio.ts`, `lib/useVoiceRecorder.ts`

- **`canRecord()`.** `MediaRecorder` and `navigator.mediaDevices.getUserMedia` must exist.
  Browsers expose `mediaDevices` only in a secure context (https or `http://localhost`, NFR-4),
  so this one check covers that too.
- **Format.** The first type the browser supports, from the list the backend accepts:
  `audio/webm;codecs=opus` → `audio/webm` → `audio/ogg;codecs=opus` → `audio/mp4`.
  - Chrome and Firefox record webm/opus; Safari records mp4.
  - If none is supported, the browser picks its own format, and the backend answers 415 if it
    cannot use it.
  - The upload is named `recording.<ext>` after the actual `blob.type`.
- **`useVoiceRecorder({ maxMs, onComplete })`** records while the component is mounted:
  - It asks for the microphone, records into one blob, and ticks every 250 ms.
  - At `maxMs` it stops by itself; the default is 90 s (FR-6).
  - `stop()` delivers `{ blob, durationMs }`. `cancel()` and unmounting discard the recording.
  - The microphone tracks are stopped in every case, including when permission is granted after
    the component is gone (e.g. React StrictMode's extra mount/unmount in development).
- **Errors.**

  | `getUserMedia` error | Message key |
  |----------------------|-------------|
  | `NotAllowedError`, `SecurityError` | `voice.denied` |
  | `NotFoundError`, `OverconstrainedError` | `voice.noMicrophone` |
  | Anything else, and a failing `MediaRecorder` constructor | `voice.failed` |

### UI

- **`MoodInput`** accepts an optional `label`, `hint`, `actions` (extra buttons next to "Find
  my song") and `autoFocus`. The review screen reuses it, so validation, the counter and
  Ctrl+Enter behave the same.
- **🎤 Record** is shown only when `meta.stt.enabled` and `canRecord()` are both true (FR-32).
  If STT is enabled but the page is not a secure context, a hint explains that voice needs
  https:// or localhost (NFR-4).
- **`VoiceRecorder`** has three states:
  - "Waiting for the microphone…" while permission is pending;
  - recording: a pulsing dot, a `0:12 / 1:30` timer (`role="timer"`), a note that recording
    stops by itself, and "Stop and transcribe" / "Cancel";
  - an error message with "Back to typing".
- **`TranscriptReview`** (FR-3):
  - an editable textarea with the transcript, focused;
  - the detected language named in the UI language (`Intl.DisplayNames`: "Polish" / "polski");
  - "Find my song", "Record again" and "Discard".
- **`HomePage` phases** follow plan 2.8:

  ```
  input → recording → transcribing → reviewing → thinking → (clarifying) → result
  ```

  - The text typed before recording is kept (`typedText`). It is restored when recording is
    cancelled, fails, hears nothing, or the transcript is discarded.
  - Cancelling "Record again" returns to the review.
  - The review shares the page's text state, so a failed submission returns to the review with
    the user's edits intact.
  - A transcript longer than 2000 characters is cut to 2000. The backend rejects longer text,
    and 90 s of speech is normally well below that.
  - "Find my song" in the review sends `{ text: <edited>, input_mode: "voice", locale,
    transcript: <original> }`, so the trace has both (FR-40).
- **Errors and retries.** A failure now carries its own "Try again" action:
  - a failed recommendation re-sends the same text (and voice data);
  - a failed transcription re-sends **the same recording**;
  - after `invalid_audio`, `audio_too_large` or `unsupported_audio_format` there is no retry,
    since re-sending cannot help;
  - after a failed clarification answer there is no button; the answer field stays.

  This replaced the step 7 condition, which would have retried a *recommendation* after a
  transcription error.
- **Messages.**
  - No speech recognized (empty transcript): an amber notice ("We didn't catch any speech…")
    instead of an error.
  - A blob over 10 MB is refused in the browser (`audio_too_large`) before uploading.
- **Translations:** a new `voice.*` section in `en.json` and `pl.json`.

### Tests

65 tests in 10 files (21 new), offline.
- `test/fakeMedia.ts` provides a `FakeMediaRecorder` that delivers fixed bytes on `stop()`,
  like the real one, and `installMicrophone({ deny?, supportedTypes? })`.
- `mockFetch` now answers `GET /api/meta` itself (STT off unless `{ sttEnabled: true }`) and
  records multipart bodies (`call.form`).

| File | Covers |
|------|--------|
| `pages/VoiceFlow.test.tsx` | full flow: record → timer → stop → upload (field `audio`, `recording.webm`, `audio/webm;codecs=opus`, the recorded bytes) → review (value, focus, "Detected language: Polish") → edit → request body with `input_mode: "voice"` and the original `transcript`; mp4 in Safari; hidden when STT is off; insecure-context hint; blocked and missing microphone; cancel (nothing sent, mic released); no speech recognized; transcription retry with the same recording; no retry for `invalid_audio`; record again and discard; failed submission keeps the edits and retries as voice; Polish UI |
| `components/VoiceRecorder.test.tsx` | (fake timers) timer and **automatic stop at 90 s**; manual stop with the duration; microphone released **immediately** on unmount; microphone granted after unmount is released; the waiting-for-permission state |
| `lib/audio.test.ts` | format preference and fallback; file names; `canRecord()` |

Mutation checks:
- Dropping `transcript` from the voice request fails 2 tests.
- Removing the stop-on-unmount call was **not** caught at first: the still-running timer
  stopped the recorder 90 s later. The unmount test now asserts the release before any time
  passes, and catches it.

## Deviations from the plan

- **Two new buttons in the review.** "Record again" and "Discard" are not named in the plan,
  but without them a bad recording could only be fixed by deleting the text.
- **No-speech notice.** An empty transcript gives a notice, not a separate review screen.
  There is nothing to edit.
- **Transcripts are cut to 2000 characters** (see above). In practice this is unlikely to
  happen.

## Issues encountered and how they were solved

1. **`HomePage` now loads `/api/meta`.** In the first run 9 step-7 tests failed: their mocks
   answered `/meta` with a recommendation. `mockFetch` now answers `/meta` itself and leaves it
   out of the recorded calls, so the other tests are unaffected.
2. **The step 7 retry condition** was wrong for transcription errors (see Errors and retries).
   It was replaced by a `Failure { error, retry? }` state.
3. **jsdom has no `MediaRecorder` or `mediaDevices`.** A fake recorder and microphone are
   installed per test and removed with `onTestFinished`. `canRecord()` checks the global
   `MediaRecorder` instead of `window.MediaRecorder`, so a stubbed global is found.
4. **Live check without a microphone or browser.** A temporary Vitest test (deleted after the
   run) did the following:
   - rendered the real `App` against the running backend;
   - made the fake recorder deliver a real Polish clip (`sample-pl.ogg`, generated with OpenAI
     TTS in step 6);
   - clicked through the whole flow.

   Node's `fetch` cannot serialize jsdom's `FormData` (the backend answered 422, with an empty
   multipart body), so the temporary test re-encoded the app's upload as multipart. It kept
   exactly the file name, type and bytes the app produced. Browsers do not have this problem.

## Live verification

The backend ran with the developer's `.env` and a temporary `DATA_DIR`; `vite` dev ran on
`:5173`.

| Check | Result |
|-------|--------|
| `GET :5173/api/meta` | `stt: {enabled: true, provider: openai, model: gpt-transcribe}` |
| Real `App` (jsdom) with the recorder delivering the PL clip as `audio/ogg;codecs=opus` | Record → timer → Stop → upload `recording.ogg`, 69,730 bytes → review shows "Miałem dziś bardzo ciężki dzień w pracy. Chciałbym posłuchać czegoś spokojnego…", "Detected language: Polish" |
| Edit (" Something instrumental, please.") → Find my song (UI in English) | 200 in 10.6 s: Brian Eno - An Ending (Ascent), English explanation |
| History via the proxy | `input_mode: voice`, the edited text stored as `input_text` |

**Not verified here: a real microphone in Chrome and Firefox.** No browser was available in
this environment. These remain for the developer to check:
- the permission prompt;
- the formats the browsers actually record (webm/opus);
- the timer in real time.

The backend accepted webm in step 6 tests, and ogg/wav live.

## Consequences

- **The voice flow is complete on `localhost`.** Using it from another device on the LAN
  needs HTTPS (NFR-4). Step 11 documents a reverse-proxy option; until then the UI shows the
  hint.
- **Step 9 (nginx)** must allow uploads up to 10 MB: `client_max_body_size` slightly above
  10m (see ADR-06).
- **Leaving the page while recording** releases the microphone and discards the recording.

## Verification

| Command / check | Result |
|-----------------|--------|
| `npm test` | 65 passed (10 files) |
| `npm run lint` (oxlint) | no findings |
| `npm run build` (`tsc -b` + `vite build`) | succeeds; 373 KB JS (117 KB gzip) |
| `npm run format:check` | all files formatted |
| Live voice flow (jsdom + real backend + real Polish clip) | see above |
| Chrome / Firefox with a real microphone | **pending: manual check by the developer** |
