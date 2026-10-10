# ADR-03: Step 3 — Music catalog clients

- Status: Accepted (amended by [ADR-03.1](step-03.1-prefer-artists-own-recording.md))
- Date: 2026-10-10
- Step: 3

## Context

Step 3 of the [implementation plan](../implementation-plan.md) builds the catalog layer that the
`verify_candidates` and `finalize` nodes (step 4) use to check that the curator's songs exist and
to get real links (FR-13, FR-14, FR-17):
- a Spotify client (Client Credentials token, track search);
- normalization and fuzzy matching of titles and artists;
- a YouTube client with quota handling and a fallback to a search URL;
- a repository for the `track_link_cache` table (created in step 1).

"Done when": respx-mocked tests cover match and no-match, token refresh, quota exceeded leading
to the fallback, and cache hits.

## Decision / What was implemented

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| httpx | 0.28.1 | Async HTTP client of both catalog clients (was already installed through the `openai` SDK; now a direct dependency) |
| rapidfuzz | 3.14.6 | Fuzzy string scoring |
| respx (dev) | 0.23.1 | Mocks httpx in tests |

### Package `app/music/`

| Module | Content |
|--------|---------|
| `matching.py` | Normalization, scoring (`score`, `rank`), `normalized_key`, `video_matches` |
| `spotify.py` | `SpotifyClient`, `SpotifyTrack`, `SpotifyMatch` |
| `youtube.py` | `YouTubeClient`, `YouTubeStatus`, `next_quota_reset` |
| `links.py` | Track and search URLs (`youtube_watch_url`, `youtube_search_url`, `spotify_search_url`) |
| `cache.py` | `TrackLinkCacheRepository` |
| `service.py` | `MusicCatalog` (cache first, then the clients) and `build_music_catalog(settings, …)` |

### Matching — `app/music/matching.py`

Both sides (the curator's candidate and the catalog's track) are normalized the same way:

- **Folding:** case-folding, NFKD with combining marks removed, plus a small map for letters NFKD
  does not decompose (`ł`→`l`, `ø`→`o`, `æ`→`ae`, …), typographic apostrophes, `&`→`and`,
  punctuation removed.
- **Variant markers removed from titles:** a bracket group or a ` - …` / ` – …` suffix is dropped
  only when it contains a marker word (`remastered`, `live`, `version`, `edit`, `mono`, `mix`,
  `feat.`, `from`, a year, …); a trailing `feat. X` is dropped too. Brackets without a marker stay
  part of the title.
- **Two title variants are compared:** without markers, and without any bracketed text, so
  "I Can't Get No Satisfaction" matches "(I Can't Get No) Satisfaction - Mono Version".
- **Artists:** a leading "The" and the word "and" are ignored. The score is the best of the whole
  strings compared (`token_sort_ratio`) and every wanted artist against every credited artist
  (`ratio`), so "Drake feat. Wizkid", "Wizkid" and "Simon & Garfunkel" all work.
- **A match needs title ≥ 85 and artist ≥ 85** (`MATCH_THRESHOLD`).
- `rank()` orders results: matches first, then by the weaker of the two scores, then by the
  similarity of the *unstripped* title (so "Hurt" beats "Hurt - Live"); ties keep the catalog's
  relevance order.
- `normalized_key(artist, title)` → `"artist|title"` (folded, markers removed): the cache key, and
  the key step 4 will use for the exclusion list.
- `video_matches()` for YouTube: the wanted title must appear in the video title
  (`partial_ratio` ≥ 85), and the artist in the video title or the channel name, compared without
  spaces (`JohnnyCashVEVO`, `Johnny Cash - Topic`).

### Spotify — `app/music/spotify.py`

- **Token:** `POST https://accounts.spotify.com/api/token` with `grant_type=client_credentials` and
  HTTP Basic auth.
  - Cached in memory and refreshed 60 s before `expires_in` runs out.
  - An `asyncio.Lock` prevents parallel refreshes.
  - If a search returns 401, the token is dropped, a new one is fetched and the search is retried
    **once**.
- **`search_track(title, artist, limit=10)`:** `GET /v1/search?type=track&market=<SPOTIFY_MARKET>`
  with `q=track:<title> artist:<artist>`.
  - `limit` must be 1–10 (Development Mode limit).
  - `"` and `:` are removed from the values (query syntax).
- **`find_track(title, artist)` → `SpotifyMatch(track, best, best_score)`:**
  1. Field-filtered search with the marker-free title.
  2. If nothing matches: a free-text search, ranked together with the first results.
  - `best` is the closest track even when it does not match, so step 4 can give the curator
    specific feedback.
- **Errors raise `CatalogUnavailableError`** (`catalog_unavailable`, 503), each with its own message
  and a log line without secrets:
  - network errors and timeouts;
  - 5xx;
  - 429 (the `Retry-After` value is logged; no waiting);
  - rejected credentials (token endpoint 400/401; the log line names `SPOTIFY_CLIENT_ID/SECRET`);
  - an unexpected response shape.
- "Nothing found" is not an error; it is an empty result.

### YouTube — `app/music/youtube.py`

- **`find_video(title, artist)`:** `GET /youtube/v3/search` with `part=snippet&type=video&videoCategoryId=10&maxResults=5&q=<artist> <title>`.
  - The API key is sent in the **`X-Goog-Api-Key` header**, so it never appears in URLs, httpx
    log lines or exception messages.
  - The first result passing `video_matches()` wins. Titles are HTML-unescaped first (the API
    returns `Don&#39;t`).
- **Never raises:** it returns a `YouTubeSearchResult` with status `found`, `not_found`,
  `quota_exceeded` or `unavailable`.
- **Quota:** error reasons `quotaExceeded` or `dailyLimitExceeded` block all further calls until
  the next quota reset.
  - The reset is midnight Pacific time, computed with a fixed UTC-8 offset, so during daylight
    saving time the client resumes one hour late, never early.
  - `rateLimitExceeded` (short-term) and other errors do not block.

### Cache — `app/music/cache.py`, `app/music/service.py`

- **`TrackLinkCacheRepository(session_factory)`:** `get(key)`, `save_spotify(key, track | None, at)`,
  `save_youtube(key, video_id | None, at)`.
  - Writes are SQLite upserts (`INSERT … ON CONFLICT DO UPDATE`) of only that service's columns.
    Spotify and YouTube results therefore share one row without overwriting each other.
  - `None` records "searched, nothing found".
  - The repository takes a session factory rather than a request session, because the graph
    nodes run outside FastAPI's dependency injection.
- **`MusicCatalog`** is the interface for step 4:
  - `lookup_spotify(title, artist)` → `SpotifyLookup(key, track | None, from_cache, closest, closest_score)`.
    Raises `CatalogUnavailableError` if Spotify is unreachable or not configured.
  - `youtube_link(title, artist)` → `YouTubeLink(url, video_id, status, from_cache)`, with
    `verified = video_id is not None`. Always returns a URL; without a video it is a YouTube
    search URL.
  - **TTL:** found results 30 days, "not found" 1 day. **Errors and quota failures are never
    cached**, so they are retried on the next request.
- **Wiring:** the app lifespan creates one shared `httpx.AsyncClient`
  (timeout `CATALOG_TIMEOUT_SECONDS`, new setting, default 10 s), closes it on shutdown, and
  exposes `app.state.catalog`. An unconfigured Spotify or YouTube is left out with a startup
  warning. The app still starts, as `/api/meta` already reports which catalogs are configured.

### Tests (201 in total, 105 new)

- `tests/music_fakes.py`: builders of Spotify and YouTube JSON responses, client factories and a
  settable `FakeClock` (time for token expiry, quota reset and TTLs). Fake credentials come from
  `tests/fakes.py`.
- `tests/conftest.py`: new `http` fixture (an `httpx.AsyncClient`, mocked through respx's
  `respx_mock` fixture, which also fails on any unmocked request).
- `test_matching.py` (48):
  - marker stripping;
  - folding (Polish letters, apostrophes);
  - artist splitting;
  - cache keys;
  - matches and non-matches, e.g. Queen vs Queen Latifah, Johnny Cash vs a cover;
  - ranking order;
  - video matching.
- `test_spotify.py` (22):
  - a match from the filtered search, with the request checked (query, market, limit, Bearer
    token, Basic auth, `grant_type`);
  - the free-text fallback;
  - no match with the closest track; no results at all;
  - query cleaning; null items; missing album art; the limit bounds;
  - the token cached across searches; refreshed exactly at the expiry margin; refreshed and
    retried after a 401 (and an error after a second 401);
  - rejected credentials (no secret in the logs);
  - 429, 5xx, bad JSON, network errors.
- `test_youtube.py` (19):
  - found, with the request checked (no key in the URL);
  - other videos skipped; HTML entities;
  - three not-found shapes;
  - quota exceeded → blocked until the reset, then calls resume;
  - reset time computation, including daylight saving time;
  - other errors → unavailable without blocking.
- `test_music_catalog.py` (16):
  - repository upserts that keep the other service's columns;
  - Spotify and YouTube cache hits (also for differently written names of the same song);
  - not-found caching and both TTLs;
  - errors and quota failures not cached;
  - quota exceeded → search URL, then recovery;
  - unconfigured services;
  - `build_music_catalog`;
  - the app exposing `app.state.catalog`.

## Deviations from the plan

| Plan | Actual | Reason |
|------|--------|--------|
| ADR-01 left open: `httpx` or `httpx2` for the catalog clients | `httpx` | respx (the planned mocking library) supports only `httpx`; `httpx` is already installed by the provider SDKs. `httpx2` stays the TestClient's dependency only. |
| "`track_link_cache` repository" | Repository plus a `MusicCatalog` service (cache first, TTLs, fallback URLs) | "Cache hits" in the done criteria need the cache-first logic. It also gives step 4 one small interface instead of three objects. |
| Repository in `db/repositories.py` (layout in 2.9) | `music/cache.py` | The layout in 2.9 lists `music/cache.py`; the repository is only used by the music layer. |
| One Spotify search per candidate | Up to two (field-filtered, then free text) | Field filters miss titles written differently from the catalog's; the second search is only made when the first finds no match. |
| YouTube: take the search result | The result must match the title and artist | Otherwise "verified" could point to a different song; a non-matching result leads to the unverified search URL. |
| — | `CATALOG_TIMEOUT_SECONDS` (default 10) | One timeout for both catalogs, in the same style as `LLM_TIMEOUT_SECONDS`. |
| — | YouTube quota blocking until the reset | Saves a pointless request per recommendation once the daily quota is gone. |
| Catalog calls with `@traceable(run_type="tool")` (2.4) | Moved to step 4 | Tracing is configured in step 4; the decorators are added together with the graph nodes that call `MusicCatalog`. |

## Issues encountered and how they were solved

1. **respx does not support `httpx2`.** Solved by using `httpx` (see the deviations).
2. **Brackets that are part of the title.** Removing every bracket group turned
   "(I Can't Get No) Satisfaction" into "Satisfaction", which no longer matched
   "I Can't Get No Satisfaction". Solved by removing only bracket groups with marker words, and
   comparing two title variants (with and without the remaining brackets).
3. **Substring-based scorers accept wrong artists.** `token_set_ratio` / `partial_ratio` give
   "Queen" vs "Queen Latifah" a score ≥ 90. Artists are therefore scored with `token_sort_ratio`
   and `ratio` (56 for that pair). Only YouTube video titles, which always contain extra words,
   use `partial_ratio`.
4. **Artist strings with separators.** Splitting "Simon & Garfunkel" gives "Simon" and
   "Garfunkel". Solved by scoring the whole strings as well as the parts and taking the maximum.
5. **NFKD does not decompose `ł`.** "Podsiadło" would not fold to "podsiadlo". Solved with a small
   letter map applied after NFKD.
6. **YouTube returns HTML-escaped titles** (`Don&#39;t`). Solved with `html.unescape`.
7. **Time zone of the quota reset.** `zoneinfo("America/Los_Angeles")` needs tz data, which slim
   Docker images may not have. A fixed UTC-8 offset is used; it errs on the safe side (see above).
8. **ruff RUF001/RUF003** on en dashes, typographic quotes and `ı` in regexes and tests. They are
   intentional, so they are written as `\u` escapes (as in ADR-02).

## Findings from the live smoke test (input for step 4)

The real `SpotifyClient` (market PL) and `YouTubeClient` were run with the developer's keys.

| Search | Result | Latency |
|--------|--------|---------|
| Hurt / Johnny Cash | match (100/100) | 423 ms (incl. token) |
| I Can't Get No Satisfaction / The Rolling Stones | match: "(I Can't Get No) Satisfaction - Mono" | 211 ms |
| Małomiasteczkowy / Dawid Podsiadło | match | 191 ms |
| Levitating / Dua Lipa; Bohemian Rhapsody / Queen | match | ~220 ms |
| Kocham Cię jak Irlandię / Kobranocka | match ("Kocham cię jak irlandię") | 276 ms |
| Completely Invented Song Title / Imaginary Band 42 | no match; closest "The Interview" (33/35) | 358 ms (two searches) |
| YouTube: Hurt; Małomiasteczkowy | found (`Johnny Cash - Hurt`, `Dawid Podsiadlo - Małomiasteczkowy`) | 250–300 ms |

- The Spotify token request and the search API work with the Development Mode app; album art is
  present.
- For "Satisfaction", Spotify's own relevance put the mono version first. It is the same song;
  acceptable.
- **A search takes 200–400 ms, so 5 candidates in sequence take 1–2 s.** Step 4 should verify the
  candidates of one attempt concurrently (`asyncio.gather`).
- The smoke test used 200 of the 10,000 daily YouTube quota units.

## Consequences

- Step 4:
  - uses `app.state.catalog` (`MusicCatalog`) in `verify_candidates` (`lookup_spotify`; `closest`
    and `closest_score` feed the curator's retry prompt) and in `finalize` (`youtube_link`, plus
    `spotify_search_url` when Spotify is unverified);
  - builds the exclusion list with `normalized_key`;
  - catches `CatalogUnavailableError` per candidate and falls back to unverified links (FR-17);
  - adds `@traceable(run_type="tool")` around the catalog calls.
- httpx logs every catalog request at INFO (`HTTP Request: GET https://api.spotify.com/v1/search?q=…`).
  This contains song names but no secrets: the Spotify token is in a header, and the YouTube key
  is in a header too. If the lines turn out to be noise, the `httpx` logger can be set to WARNING
  in `logging_config.py`.
- Cached "found" entries are trusted for 30 days. If the matching rules are changed, the
  `track_link_cache` table can simply be emptied (it holds no user data).
- New setting `CATALOG_TIMEOUT_SECONDS` in `.env.example`.

## Verification

| Command / check | Result |
|-----------------|--------|
| `uv run pytest -q` | 201 passed, no warnings |
| `uv run ruff check .` / `ruff format --check .` | clean |
| `uv run mypy` (strict) | no issues in 47 source files |
| Live: `SpotifyClient.find_track` for 7 songs, `YouTubeClient.find_video` for 2 | see the findings above |
| Live: `create_app` with the developer's `.env` | starts; `/api/meta` → `catalogs: {spotify: true, youtube: true}`; `app.state.catalog` has both clients |
