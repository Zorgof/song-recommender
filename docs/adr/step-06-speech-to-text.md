# ADR-06: Step 6 — Speech-to-text (OpenAI)

- Status: Accepted
- Date: 2026-10-11
- Step: 6

## Context

Step 6 of the [implementation plan](../implementation-plan.md) adds the backend half of voice
input (FR-2, FR-3, FR-30–FR-32, section 2.7):
- an `STTProvider` interface and an OpenAI implementation (`OpenAISTT`) that use the shared
  `OPENAI_API_KEY`;
- `POST /api/transcriptions` with size and type validation;
- `STT_PROVIDER=none`, which turns STT off.

The language is detected, not taken from the UI locale. The user may speak Polish with the UI
in English. Audio never goes to LangSmith; transcripts do (NFR-5, FR-40).

"Done when": backend tests mock the OpenAI call, and a manual check transcribes a sample
Polish and a sample English clip.

## Decision / What was implemented

### Model: `gpt-transcribe`

- Checked against the OpenAI docs (speech-to-text guide, model page) and the installed `openai`
  SDK 3.26:

  | Model | Notes |
  |-------|-------|
  | `gpt-transcribe` | OpenAI's recommended model for recorded speech; returns the detected `languages`; $0.0045/min |
  | `gpt-4o-transcribe`, `gpt-4o-mini-transcribe` | Older; `json` response only, no language |
  | `whisper-1` | Timestamps and translation; `verbose_json` gives a language **name** (`"polish"`) |
  | `gpt-4o-transcribe-diarize` | Speaker labels; not needed here |

- `STT_MODEL` now defaults to `gpt-transcribe` (`Settings.stt_model: str`, was `str | None`), and
  `.env.example` sets it explicitly. An empty `STT_MODEL=` line in `.env` falls back to the
  default (`env_ignore_empty`).

### `app/stt/`

| File | Contents |
|------|----------|
| `base.py` | `Transcript(text, language, duration_s)`; the `STTProvider` protocol (`name`, `transcribe(audio, mime)`, `aclose()`); `AUDIO_FORMATS` (accepted content type → file extension); `base_content_type()` |
| `openai_stt.py` | `OpenAISTT`: one `audio.transcriptions.create` call with the `json` response format |
| `factory.py` | `build_stt_provider(settings)`: the provider, or `None` when STT is disabled |

- **Request.** `OpenAISTT` sends `file=("recording.<ext>", bytes, mime)`. The API identifies
  the format from the file name and the content type. No `language`, `languages` or `prompt` is
  sent: the language is detected.
- **Response.**
  - `text` is trimmed.
  - `language` is the first entry of `languages`, lower-cased (only `gpt-transcribe` returns
    it).
  - `duration_s` comes from `usage.seconds` when usage is billed by duration.
  - Fields the model does not return are `None`.
- **Client.** `openai.AsyncOpenAI` is created from `Settings` with the key passed explicitly, as
  in the LLM layer (ADR-02). It reuses `LLM_TIMEOUT_SECONDS` and `LLM_MAX_RETRIES`, so there are
  no new env variables. The client is created in the lifespan (`app.state.stt`) and closed on
  shutdown.
- **Errors.**

  | OpenAI error | Result |
  |--------------|--------|
  | `400` with `param == "file"` (corrupted, unsupported or too short audio) | `InvalidAudioError` → 422 `invalid_audio`, logged as a warning |
  | Any other API error: wrong model id (404), bad key (401), rate limit, 5xx, network, timeout | `STTUnavailableError` → 503 `stt_unavailable`, logged as an error with the class, status and code |

  The error message from OpenAI is never logged.

### `POST /api/transcriptions` — `app/api/transcriptions.py`

- **Body.** Multipart, field `audio`. **Response:** `{text, language, duration_s}`.
- **Checks, in this order, all before the provider is called:**

  | Check | Error |
  |-------|-------|
  | Content type, without parameters such as `;codecs=opus` and case-insensitive, is one of `audio/webm`, `audio/ogg`, `audio/mp4`, `audio/wav`, `audio/x-wav`, `audio/wave` | 415 `unsupported_audio_format` |
  | Size ≤ 10 MB (FR-6). The upload is read with a limit of 10 MB + 1 byte | 413 `audio_too_large` |
  | File is not empty | 422 `invalid_audio` |
  | `audio` field is present | 422 `validation_error` (FastAPI) |

- **STT disabled.** `STT_PROVIDER=none`, or no OpenAI key → the `get_stt` dependency raises
  503 `stt_unavailable` ("Speech-to-text is disabled."). `/api/meta` reports
  `stt.enabled=false`.
- **Empty transcript** (silence) → 200 with `text: ""`. The frontend shows "nothing was
  recognized"; this is not an error.
- **Logging.** One INFO line per transcription with provider, mime, size, language, duration,
  character count and elapsed time. The transcript and the audio are not logged.
- **Not traced in LangSmith.** Tracing the call could put the audio bytes into a run's inputs
  (NFR-5). The transcript reaches the trace with the recommendation request; see the next
  section.

### The raw transcript in the trace (FR-40)

- `POST /api/recommendations` accepts an optional `transcript` field: the text returned by
  `/api/transcriptions`, before the user's edits. Up to 5000 characters, trimmed.
- It is only allowed with `input_mode: "voice"`; otherwise 422.
- It is passed to `RecommendationRunner.start(transcript=…)`. That parameter already existed
  (ADR-04), but nothing set it until now.
- The root run then has both `user_input` (the edited, submitted text) and `transcript`.

### Other changes

- New error classes in `app/errors.py`: `AudioTooLargeError` (413), `UnsupportedAudioFormatError`
  (415), `InvalidAudioError` (422). The plan's error-code list (2.6) is updated.
- `/api/meta`: `stt` now includes `model` (the STT model when enabled, otherwise `null`). Like
  the LLM tiers, it contains no secrets.
- Dependencies: `openai` and `python-multipart` are now direct dependencies.
  - `openai` was only a transitive dependency of `langchain-openai`.
  - FastAPI needs `python-multipart` for `UploadFile`.
- Startup log line: `stt=openai|None`.
- `backend/README.md`: layout, API table, error codes, an STT section and a curl command for
  the manual check.

## Deviations from the plan

- **`language` and `duration_s` are nullable.**
  - Section 2.7 defines `Transcript(text, language, duration_s)` as always present, but only
    some models return them.
  - `duration_s` is the **billed** duration (whole seconds, see the live check). It is
    approximate, and the frontend already knows the recording length from its own timer.
- **Three new error codes** (`audio_too_large`, `unsupported_audio_format`, `invalid_audio`)
  instead of `validation_error` for everything. The frontend can then say *what* is wrong with
  a recording in the user's language.
- **`transcript` field on `POST /api/recommendations`.** It is not in the plan's API table, but
  FR-40 requires the transcript in the trace, and the runner already accepted it.
- **`mp4` is accepted with `audio/mp4` only.** Safari's MediaRecorder uses `audio/mp4`.
  `video/*` types are rejected; step 8 can add aliases if a browser needs them.

## Issues encountered and how they were solved

1. **The `openai` SDK 3.x uses `httpx2`, not `httpx`.** respx (used for the catalog clients)
   cannot intercept it. The `OpenAISTT` tests pass an `httpx2.AsyncClient` with
   `httpx2.MockTransport` to `AsyncOpenAI(http_client=…)`. This tests the real SDK request
   (multipart body, path, model, file name) and the error classes. The handler type must be
   `Callable[..., Coroutine[...]]` for mypy (not `Awaitable`).
2. **Telling bad audio apart from a bad configuration.** Both come back as HTTP 400 or 404. Only
   `param == "file"` means the recording itself is wrong (`invalid_audio`). Everything else is
   a server-side problem (`stt_unavailable`), so a wrong `STT_MODEL` is not shown to the user
   as "your recording is broken". Checked live: a wrong model gives 404 `model_not_found` →
   503.
3. **`python-multipart` was missing.** FastAPI refuses to register an `UploadFile` route without
   it. Added with `uv add`.
4. **Manual check without recorded clips.** Sample PL and EN clips were generated with OpenAI
   TTS (`gpt-4o-mini-tts`) in the session's scratch directory. They were not committed. A
   recording from a real microphone in the browser is checked in step 8.

## Live verification

Uvicorn ran with the developer's `.env` (`STT_MODEL` empty → default `gpt-transcribe`) and
`DATA_DIR` in a temporary directory; calls were made with curl.

| Call | Result |
|------|--------|
| `GET /api/meta` | `stt: {enabled: true, provider: openai, model: gpt-transcribe}` |
| PL clip, `audio/ogg;codecs=opus` (68 KB) | 200 in 1.0 s; exact Polish text, `language: "pl"`, `duration_s: 8.0` |
| EN clip, ogg (45 KB) | 200 in 0.8 s; exact text, `language: "en"`, `duration_s: 5.0` |
| PL / EN clips, `audio/wav` | 200; same texts, `pl` / `en` (EN wav reported 7.0 s: billed, not exact, duration) |
| 20 KB of random bytes as `audio/webm` | 422 `invalid_audio` (OpenAI `invalid_value`, `param=file`) |
| A truncated 2 KB wav | 422 `invalid_audio` |
| `STT_MODEL=no-such-model` | 503 `stt_unavailable`; log: `NotFoundError status=404 code=model_not_found` |
| Voice flow: PL transcript + edit → `POST /api/recommendations` (`input_mode=voice`, UI `en`, `transcript`) | 200 `completed` in 12 s: Ludovico Einaudi - Nuvole Bianche, both links verified, **English** explanation |
| LangSmith `read_run` of that request | root run `recommend_song`, tags `locale:en`, `voice`; inputs `transcript` (raw) and `user_input` (edited) |

## Consequences

- **Frontend, step 7.**
  - Maps the new codes `audio_too_large`, `unsupported_audio_format` and `invalid_audio` to
    localized messages.
  - Hides the microphone when `meta.stt.enabled` is false.
- **Frontend, step 8.**
  - Sends the `MediaRecorder` blob as the `audio` field. Its type keeps parameters such as
    `audio/webm;codecs=opus`; they are accepted.
  - Treats an empty `text` as "nothing recognized".
  - Submits the edited text with `input_mode: "voice"` and the original text as `transcript`.
  - Uses its own timer for the 90 s cap. `duration_s` is informational.
- **Upload size.** Starlette buffers the whole multipart body (spooled to disk) before the
  10 MB check runs. That is fine for one local user. nginx (step 9) should set
  `client_max_body_size` a little above 10 MB, so larger uploads are refused before they
  reach the backend.
- **Another STT provider** (e.g. local Whisper) is a new class with `transcribe`/`aclose` plus a
  `case` in `build_stt_provider`.
- **Accuracy tuning, if needed later.** `gpt-transcribe` accepts `languages` (candidate
  languages, e.g. `["pl", "en"]`) and `keywords`. Neither is sent now, as the plan asks.
  Restricting the candidates to PL/EN is an option if short clips are misdetected.

## Verification

| Command / check | Result |
|-----------------|--------|
| `uv run pytest -q` | 296 passed (34 new), no warnings |
| `uv run ruff check .` / `ruff format --check .` | clean |
| `uv run mypy` (strict) | no issues in 83 source files |
| Live STT and voice flow with real keys | see above |
