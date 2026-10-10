"""Graph state and the dependencies the nodes receive through LangGraph's runtime context.

The state holds only JSON-like values (dicts, lists, strings, numbers): it is stored in the
checkpointer between the clarifying question and the answer, and plain values serialize
without registering custom types. Nodes validate them back into the Pydantic schemas.
"""

import operator
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, TypedDict

from app.agents.prompt_loader import PromptLibrary
from app.agents.schemas import Locale
from app.db.repositories import RecommendationRepository
from app.llm.models import ModelRegistry, Tier
from app.music.service import SpotifyLookup, YouTubeLink

# At most this many curator attempts per request (the first one plus two retries).
MAX_CURATION_ATTEMPTS = 3
# Songs the curator is asked for in each attempt. 3 rather than 5: the curator's output
# dominates latency (ADR-04.1), and verification keeps two fallbacks per attempt.
CANDIDATE_COUNT = 3


def merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


class Escalation(TypedDict):
    node: str
    from_tier: Tier
    to_tier: Tier
    reason: str


class RejectedCandidate(TypedDict):
    attempt: int
    title: str
    artist: str
    reason: str


class GraphState(TypedDict, total=False):
    # --- Input ---
    request_id: str
    locale: Locale
    user_input: str
    input_mode: str
    # Recently recommended songs: [{"title": ..., "artist": ...}], newest first.
    excluded_tracks: list[dict[str, str]]

    # --- Clarification (at most once) ---
    clarification_question: str | None
    clarification_answer: str | None

    # --- Agents ---
    routing: dict[str, Any]  # RoutingDecision
    need_profile: dict[str, Any]  # NeedProfile
    curation_attempts: int
    candidates: list[dict[str, Any]]  # SongCandidate, latest attempt, best first
    # Latest attempt: [{"candidate": SongCandidate, "track": SpotifyTrack fields}]
    verified: list[dict[str, Any]]
    # All attempts; fed back to the curator.
    rejected: Annotated[list[RejectedCandidate], operator.add]
    # Spotify could not be reached in the latest attempt; retrying would not help.
    catalog_unavailable: bool

    # --- Observability ---
    escalations: Annotated[list[Escalation], operator.add]
    # Model that answered, per node.
    models_used: Annotated[dict[str, str], merge_dicts]

    # --- Output ---
    recommendation: dict[str, Any]  # Recommendation


class Catalog(Protocol):
    """What the graph needs from the music catalog (implemented by MusicCatalog)."""

    async def lookup_spotify(self, title: str, artist: str) -> SpotifyLookup: ...

    async def youtube_link(self, title: str, artist: str) -> YouTubeLink: ...


@dataclass(frozen=True)
class AgentDeps:
    """Passed to every run as LangGraph's runtime context; never checkpointed."""

    models: ModelRegistry
    catalog: Catalog
    prompts: PromptLibrary
    repository: RecommendationRepository
