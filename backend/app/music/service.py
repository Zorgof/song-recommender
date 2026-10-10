"""Catalog lookups for the agent graph: cache first, then the Spotify / YouTube clients.

- `lookup_spotify` verifies a curator candidate. "Not found" is a normal result; an unreachable
  or unconfigured Spotify raises CatalogUnavailableError, so the caller can tell the two apart.
- `youtube_link` always returns a link: the video when it is found, otherwise a search URL
  marked unverified (quota used up, API error, not configured, nothing found).

Found and not-found lookups are cached; errors are not, so they are retried next time.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Settings
from app.db.models import TrackLinkCache
from app.errors import CatalogUnavailableError
from app.music.cache import TrackLinkCacheRepository
from app.music.links import youtube_search_url, youtube_watch_url
from app.music.matching import MatchScore, normalized_key
from app.music.spotify import SpotifyClient, SpotifyTrack
from app.music.youtube import YouTubeClient, YouTubeStatus

logger = logging.getLogger(__name__)

# How long cached lookups are trusted. Found tracks and videos rarely disappear; "not found"
# expires sooner, as catalogs grow and the matching may be tuned.
FOUND_TTL = timedelta(days=30)
NOT_FOUND_TTL = timedelta(days=1)


@dataclass(frozen=True)
class SpotifyLookup:
    key: str
    # The matching track, or None when the song was not found.
    track: SpotifyTrack | None
    from_cache: bool
    # The closest non-matching track of a live search, for the curator's feedback.
    closest: SpotifyTrack | None = None
    closest_score: MatchScore | None = None


@dataclass(frozen=True)
class YouTubeLink:
    url: str
    video_id: str | None
    status: YouTubeStatus
    from_cache: bool

    @property
    def verified(self) -> bool:
        return self.video_id is not None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_fresh(fetched_at: datetime | None, found: bool, now: datetime) -> bool:
    if fetched_at is None:
        return False
    return now - fetched_at < (FOUND_TTL if found else NOT_FOUND_TTL)


class MusicCatalog:
    def __init__(
        self,
        spotify: SpotifyClient | None,
        youtube: YouTubeClient | None,
        cache: TrackLinkCacheRepository,
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._spotify = spotify
        self._youtube = youtube
        self._cache = cache
        self._now = now

    async def lookup_spotify(self, title: str, artist: str) -> SpotifyLookup:
        key = normalized_key(artist, title)
        cached = await self._cache.get(key)
        if cached and _is_fresh(
            cached.spotify_fetched_at, cached.spotify_track_id is not None, self._now()
        ):
            return SpotifyLookup(key, _cached_track(cached), from_cache=True)

        if self._spotify is None:
            raise CatalogUnavailableError("Spotify is not configured.")
        match = await self._spotify.find_track(title, artist)
        await self._cache.save_spotify(key, match.track, self._now())
        return SpotifyLookup(
            key,
            match.track,
            from_cache=False,
            closest=None if match.track else match.best,
            closest_score=None if match.track else match.best_score,
        )

    async def youtube_link(self, title: str, artist: str) -> YouTubeLink:
        key = normalized_key(artist, title)
        cached = await self._cache.get(key)
        if cached and _is_fresh(
            cached.youtube_fetched_at, cached.youtube_video_id is not None, self._now()
        ):
            if cached.youtube_video_id:
                return YouTubeLink(
                    youtube_watch_url(cached.youtube_video_id),
                    cached.youtube_video_id,
                    YouTubeStatus.FOUND,
                    from_cache=True,
                )
            return YouTubeLink(
                youtube_search_url(title, artist), None, YouTubeStatus.NOT_FOUND, from_cache=True
            )

        if self._youtube is None:
            return YouTubeLink(
                youtube_search_url(title, artist), None, YouTubeStatus.UNAVAILABLE, False
            )
        result = await self._youtube.find_video(title, artist)
        if result.status in (YouTubeStatus.FOUND, YouTubeStatus.NOT_FOUND):
            await self._cache.save_youtube(key, result.video_id, self._now())
        if result.video_id:
            return YouTubeLink(
                youtube_watch_url(result.video_id), result.video_id, result.status, False
            )
        return YouTubeLink(youtube_search_url(title, artist), None, result.status, False)


def _cached_track(row: TrackLinkCache) -> SpotifyTrack | None:
    if row.spotify_track_id is None or row.spotify_url is None:
        return None
    return SpotifyTrack(
        id=row.spotify_track_id,
        title=row.spotify_title or "",
        artists=(row.spotify_artist,) if row.spotify_artist else (),
        url=row.spotify_url,
        album_art_url=row.album_art_url,
    )


def build_music_catalog(
    settings: Settings, http: httpx.AsyncClient, cache: TrackLinkCacheRepository
) -> MusicCatalog:
    """Catalog clients for the configured services; an unconfigured one is left out."""
    spotify = None
    if settings.spotify_client_id and settings.spotify_client_secret:
        spotify = SpotifyClient(
            http,
            settings.spotify_client_id,
            settings.spotify_client_secret.get_secret_value(),
            settings.spotify_market,
        )
    else:
        logger.warning("Spotify is not configured; recommendations will be unverified")
    youtube = None
    if settings.youtube_api_key:
        youtube = YouTubeClient(http, settings.youtube_api_key.get_secret_value())
    else:
        logger.warning("YouTube is not configured; YouTube links will be search links")
    return MusicCatalog(spotify, youtube, cache)
