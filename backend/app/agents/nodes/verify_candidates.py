"""verify_candidates: checks the curator's songs against Spotify (no LLM).

A candidate is verified when Spotify has a matching track that was not recommended recently.
Lookups of one attempt run concurrently. If Spotify cannot be reached, the attempt ends without
verified songs and `catalog_unavailable` stops further retries (they would not help).
"""

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from langgraph.runtime import Runtime
from langsmith import traceable

from app.agents.nodes.common import without_catalog
from app.agents.schemas import SongCandidate
from app.agents.state import (
    MAX_CURATION_ATTEMPTS,
    AgentDeps,
    Catalog,
    GraphState,
    RejectedCandidate,
)
from app.errors import CatalogUnavailableError
from app.music.matching import normalized_key
from app.music.service import SpotifyLookup

logger = logging.getLogger(__name__)

REASON_EXCLUDED = "recommended recently"
REASON_DUPLICATE = "duplicate of another candidate"


@traceable(run_type="tool", name="spotify_lookup", process_inputs=without_catalog)
async def spotify_lookup(catalog: Catalog, title: str, artist: str) -> SpotifyLookup:
    return await catalog.lookup_spotify(title, artist)


def not_found_reason(lookup: SpotifyLookup) -> str:
    if lookup.closest is None or lookup.closest_score is None:
        return "not found on Spotify"
    score = lookup.closest_score
    return (
        f"not found on Spotify (closest: {lookup.closest.artist} - {lookup.closest.title}, "
        f"title similarity {score.title:.0f}/100, artist similarity {score.artist:.0f}/100)"
    )


async def verify_candidates(state: GraphState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    catalog = runtime.context.catalog
    attempt = state["curation_attempts"]
    excluded = {normalized_key(t["artist"], t["title"]) for t in state.get("excluded_tracks", [])}
    candidates = [SongCandidate.model_validate(c) for c in state["candidates"]]

    rejected: list[RejectedCandidate] = []

    def reject(candidate: SongCandidate, reason: str) -> None:
        rejected.append(
            RejectedCandidate(
                attempt=attempt, title=candidate.title, artist=candidate.artist, reason=reason
            )
        )

    to_check: list[SongCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalized_key(candidate.artist, candidate.title)
        if key in excluded:
            reject(candidate, REASON_EXCLUDED)
        elif key in seen:
            reject(candidate, REASON_DUPLICATE)
        else:
            seen.add(key)
            to_check.append(candidate)

    results = await asyncio.gather(
        *(spotify_lookup(catalog, c.title, c.artist) for c in to_check), return_exceptions=True
    )

    verified: list[dict[str, Any]] = []
    unavailable = False
    for candidate, result in zip(to_check, results, strict=True):
        if isinstance(result, CatalogUnavailableError):
            unavailable = True
            continue
        if isinstance(result, BaseException):
            raise result
        track = result.track
        if track is None:
            reject(candidate, not_found_reason(result))
        elif normalized_key(track.artist, track.title) in excluded:
            reject(candidate, REASON_EXCLUDED)
        else:
            verified.append({"candidate": candidate.model_dump(), "track": asdict(track)})

    if unavailable:
        logger.warning("Spotify unavailable during verification", extra={"attempt": attempt})
    return {"verified": verified, "rejected": rejected, "catalog_unavailable": unavailable}


def after_verification(state: GraphState) -> str:
    if state["verified"] or state.get("catalog_unavailable"):
        return "finalize"
    if state["curation_attempts"] < MAX_CURATION_ATTEMPTS:
        return "music_curator"
    return "finalize"
