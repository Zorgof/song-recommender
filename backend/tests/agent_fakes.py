"""Fakes and builders for agent graph tests: LLM answers, a catalog, a wired-up runner."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.graph import build_graph
from app.agents.prompt_loader import PromptLibrary
from app.agents.runner import RecommendationRunner
from app.agents.state import AgentDeps
from app.db.repositories import RecommendationRepository
from app.errors import CatalogUnavailableError
from app.llm.models import ModelOptions, ModelRegistry, ModelSpec
from app.music.links import youtube_search_url, youtube_watch_url
from app.music.matching import normalized_key
from app.music.service import SpotifyLookup, YouTubeLink
from app.music.spotify import SpotifyTrack
from app.music.youtube import YouTubeStatus
from app.observability.tracing import Tracing
from tests.conftest import make_app_settings
from tests.fake_llm import SchemaRoutedChatModel

SessionFactory = async_sessionmaker[AsyncSession]


def need_profile(**overrides: Any) -> dict[str, Any]:
    return {
        "summary": "The user is tired after work and wants to unwind.",
        "summary_localized": "You are tired after work and want to unwind.",
        "emotions": ["tired", "relieved"],
        "energy": 0.2,
        "valence": 0.5,
        "day_context": "Long workday is over; evening at home ahead.",
        "goal": "calm",
        "target_energy": 0.25,
        "musical_hints": ["acoustic", "slow tempo"],
        "avoid": ["aggressive drums"],
        "confidence": 0.8,
        "needs_clarification": False,
        "clarification_question": None,
        "rationale": "Explicit tiredness and a wish to relax point to calm music.",
        **overrides,
    }


def clarification_profile(question: str) -> dict[str, Any]:
    return need_profile(
        needs_clarification=True,
        clarification_question=question,
        confidence=0.2,
        summary="Too little information about the user's mood.",
    )


def candidate(rank: int, title: str, artist: str, explanation: str = "") -> dict[str, Any]:
    return {
        "rank": rank,
        "title": title,
        "artist": artist,
        "rationale": f"{title} is slow and warm.",
        "explanation": explanation or f"{title} will help you slow down.",
        "fit_notes": "Low energy, gentle mood.",
    }


def curator_output(*songs: tuple[str, str] | dict[str, Any]) -> dict[str, Any]:
    """Candidates from (title, artist) pairs (ranked in order) or full candidate dicts."""
    return {
        "candidates": [
            song if isinstance(song, dict) else candidate(rank, *song)
            for rank, song in enumerate(songs, start=1)
        ]
    }


def track(title: str, artist: str, track_id: str | None = None) -> SpotifyTrack:
    track_id = track_id or normalized_key(artist, title).replace(" ", "-").replace("|", "_")
    return SpotifyTrack(
        id=track_id,
        title=title,
        artists=(artist,),
        url=f"https://open.spotify.com/track/{track_id}",
        album_art_url=f"https://i.scdn.co/image/{track_id}",
    )


@dataclass
class FakeCatalog:
    """Spotify knows `tracks` (by the candidate's normalized key); YouTube knows `videos`."""

    tracks: dict[str, SpotifyTrack] = field(default_factory=dict)
    videos: dict[str, str] = field(default_factory=dict)
    spotify_down: bool = False
    spotify_lookups: list[tuple[str, str]] = field(default_factory=list)
    youtube_lookups: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def knowing(cls, *tracks: SpotifyTrack, videos: dict[str, str] | None = None) -> FakeCatalog:
        return cls(
            tracks={normalized_key(t.artist, t.title): t for t in tracks}, videos=videos or {}
        )

    async def lookup_spotify(self, title: str, artist: str) -> SpotifyLookup:
        self.spotify_lookups.append((title, artist))
        if self.spotify_down:
            raise CatalogUnavailableError("Spotify could not be reached.")
        key = normalized_key(artist, title)
        return SpotifyLookup(key, self.tracks.get(key), from_cache=False)

    async def youtube_link(self, title: str, artist: str) -> YouTubeLink:
        self.youtube_lookups.append((title, artist))
        video = self.videos.get(normalized_key(artist, title))
        if video:
            return YouTubeLink(youtube_watch_url(video), video, YouTubeStatus.FOUND, False)
        return YouTubeLink(youtube_search_url(title, artist), None, YouTubeStatus.NOT_FOUND, False)


@dataclass
class Harness:
    runner: RecommendationRunner
    repository: RecommendationRepository
    light: SchemaRoutedChatModel
    heavy: SchemaRoutedChatModel
    catalog: FakeCatalog
    deps: AgentDeps


def make_registry(tmp_path: Path, light: BaseChatModel, heavy: BaseChatModel) -> ModelRegistry:
    models = {"light-model": light, "heavy-model": heavy}

    def factory(spec: ModelSpec, _: ModelOptions) -> BaseChatModel:
        return models[spec.model]

    settings = make_app_settings(
        tmp_path, llm_light="openai:light-model", llm_heavy="openai:heavy-model"
    )
    return ModelRegistry(settings, factory)


def make_harness(
    tmp_path: Path,
    session_factory: SessionFactory,
    *,
    light: dict[str, list[Any]],
    heavy: dict[str, list[Any]] | None = None,
    catalog: FakeCatalog | None = None,
    checkpointer: BaseCheckpointSaver[str] | None = None,
    tracing: Tracing | None = None,
    history_exclude_last_n: int = 50,
) -> Harness:
    light_model = SchemaRoutedChatModel(model_name="light-v1", responses=light)
    heavy_model = SchemaRoutedChatModel(model_name="heavy-v1", responses=heavy or {})
    repository = RecommendationRepository(session_factory)
    catalog = catalog or FakeCatalog()
    deps = AgentDeps(
        models=make_registry(tmp_path, light_model, heavy_model),
        catalog=catalog,
        prompts=PromptLibrary.load(),
        repository=repository,
    )
    runner = RecommendationRunner(
        build_graph(checkpointer or InMemorySaver()),
        deps,
        tracing or Tracing("test-project", None),
        history_exclude_last_n=history_exclude_last_n,
    )
    return Harness(runner, repository, light_model, heavy_model, catalog, deps)
