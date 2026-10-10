# ADR-03.1: Step 3 — Prefer the artist's own recording when matches tie

- Status: Accepted
- Date: 2026-10-10
- Step: 3 (additional ADR #1)
- Amends: [ADR-03](step-03-music-catalog-clients.md) (ranking of Spotify search results in `matching.rank`)

## Context

The live run of step 4 recommended "An Ending (Ascent)" by Brian Eno. The chosen Spotify track
was credited to "Brian Eno, Tyler Rix, Tolga Kashif" (a later collaboration), not to Brian Eno
alone. The field-filtered search returned:

| # | Spotify title | Artists | title / artist / exact title |
|---|---------------|---------|------------------------------|
| 1 | An Ending (Ascent) | Brian Eno, Tyler Rix, Tolga Kashif | 100 / 100 / 100 |
| 2 | An Ending (Ascent) - Remastered 2005 | Brian Eno | 100 / 100 / 67 |
| 3 | An Ending (Ascent) - Remastered 2019 | Brian Eno | 100 / 100 / 67 |

All of them match: the artist score accepts any credited artist, so that "Drake feat. Wizkid" or
"Wizkid" both match "One Dance" (ADR-03). The only tie-breaker was the similarity of the
unstripped title, and the collaboration has no "Remastered" suffix, so it won.

## Decision / What was implemented

- `MatchScore` gets a new field `exact_artist`: the wanted artist string against **all**
  credited artists together (`token_sort_ratio` after normalization). For the example: 100 for
  Brian Eno alone, about 45 for the collaboration.
- `rank()` sorts by: match, then the weaker of title and artist, **then `exact_artist`**, then
  `exact_title`, then the catalog's order.
  - Among equally good matches, a recording credited exactly to the wanted artist(s) is
    therefore preferred.
  - "Hurt" is still preferred over "Hurt - Live" when both are by the same artist.
- Whether a track matches at all is unchanged (title ≥ 85 and artist ≥ 85).

## Deviations from the plan

None; this refines the ranking that ADR-03 introduced.

## Issues encountered and how they were solved

- The first attempt to reproduce the case live failed with `httpx.ConnectTimeout`. The
  diagnostic script used httpx's default 5 s timeout; the app uses `CATALOG_TIMEOUT_SECONDS`
  (10 s). The client turned the timeout into `CatalogUnavailableError` as designed. A retry
  with a longer timeout worked.

## Consequences

- Cache entries written before this change may hold a collaboration where the artist's own
  recording exists. They expire after 30 days, or the `track_link_cache` table can be emptied.
  The developer's `data/app.db` was not used by the live runs (they used a temporary directory).

## Verification

| Command / check | Result |
|-----------------|--------|
| New test `test_rank_prefers_the_artists_own_recording_over_a_collaboration` | passes |
| `uv run pytest -q` / `ruff` / `mypy` | 238 passed / clean / no issues |
| Live: `rank()` over the real Spotify results above | "An Ending (Ascent) - Remastered 2005" by Brian Eno first |
