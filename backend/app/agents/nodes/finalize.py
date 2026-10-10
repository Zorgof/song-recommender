"""finalize: picks the song, looks up YouTube, persists the result (no LLM).

The highest-ranked verified candidate wins. Without one (Spotify unreachable, or every attempt
rejected), the curator's best remaining candidate is returned with search links marked
unverified (FR-17).
"""

from typing import Any

from langgraph.runtime import Runtime
from langsmith import traceable

from app.agents.nodes.common import without_catalog
from app.agents.schemas import NeedProfile, Recommendation, SongCandidate
from app.agents.state import AgentDeps, Catalog, GraphState
from app.music.links import spotify_search_url
from app.music.matching import normalized_key
from app.music.service import YouTubeLink
from app.music.spotify import SpotifyTrack


@traceable(run_type="tool", name="youtube_lookup", process_inputs=without_catalog)
async def youtube_lookup(catalog: Catalog, title: str, artist: str) -> YouTubeLink:
    return await catalog.youtube_link(title, artist)


def fallback_candidate(state: GraphState) -> SongCandidate:
    """Best candidate of the latest attempt that was not recommended recently."""
    candidates = [SongCandidate.model_validate(c) for c in state["candidates"]]
    excluded = {normalized_key(t["artist"], t["title"]) for t in state.get("excluded_tracks", [])}
    for candidate in candidates:
        if normalized_key(candidate.artist, candidate.title) not in excluded:
            return candidate
    return candidates[0]


async def finalize(state: GraphState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    deps = runtime.context
    profile = NeedProfile.model_validate(state["need_profile"])

    track: SpotifyTrack | None = None
    if state.get("verified"):
        best = min(state["verified"], key=lambda v: v["candidate"]["rank"])
        candidate = SongCandidate.model_validate(best["candidate"])
        track = SpotifyTrack(**{**best["track"], "artists": tuple(best["track"]["artists"])})
        title, artist = track.title, track.artist
    else:
        candidate = fallback_candidate(state)
        title, artist = candidate.title, candidate.artist

    youtube = await youtube_lookup(deps.catalog, title, artist)
    recommendation = Recommendation(
        request_id=state["request_id"],
        locale=state["locale"],
        title=title,
        artist=artist,
        album_art_url=track.album_art_url if track else None,
        spotify_url=track.url if track else spotify_search_url(title, artist),
        spotify_track_id=track.id if track else None,
        youtube_url=youtube.url,
        spotify_verified=track is not None,
        youtube_verified=youtube.verified,
        explanation=candidate.explanation,
        need_summary=profile.summary_localized,
    )

    await deps.repository.complete(
        state["request_id"],
        title=recommendation.title,
        artist=recommendation.artist,
        album_art_url=recommendation.album_art_url,
        spotify_track_id=recommendation.spotify_track_id,
        spotify_url=recommendation.spotify_url,
        spotify_verified=recommendation.spotify_verified,
        youtube_url=recommendation.youtube_url,
        youtube_verified=recommendation.youtube_verified,
        explanation=recommendation.explanation,
        need_summary=recommendation.need_summary,
        need_profile=state["need_profile"],
        models_used=state.get("models_used", {}),
        escalated=bool(state.get("escalations")),
    )
    return {"recommendation": recommendation.model_dump()}
