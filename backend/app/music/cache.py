"""Repository of the `track_link_cache` table: catalog lookups per normalized "artist|title".

Spotify and YouTube results of a key are written independently (upserts of their own columns),
so a YouTube lookup does not overwrite a cached Spotify result and vice versa.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import TrackLinkCache
from app.music.spotify import SpotifyTrack


class TrackLinkCacheRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, key: str) -> TrackLinkCache | None:
        async with self._session_factory() as session:
            return await session.get(TrackLinkCache, key)

    async def save_spotify(
        self, key: str, track: SpotifyTrack | None, fetched_at: datetime
    ) -> None:
        """Store a Spotify lookup; `track=None` records "searched, nothing matched"."""
        await self._upsert(
            key,
            {
                "spotify_track_id": track.id if track else None,
                "spotify_url": track.url if track else None,
                "spotify_title": track.title if track else None,
                "spotify_artist": track.artist if track else None,
                "album_art_url": track.album_art_url if track else None,
                "spotify_fetched_at": fetched_at,
            },
        )

    async def save_youtube(self, key: str, video_id: str | None, fetched_at: datetime) -> None:
        """Store a YouTube lookup; `video_id=None` records "searched, nothing matched"."""
        await self._upsert(key, {"youtube_video_id": video_id, "youtube_fetched_at": fetched_at})

    async def _upsert(self, key: str, values: dict[str, Any]) -> None:
        statement = insert(TrackLinkCache).values(normalized_key=key, **values)
        statement = statement.on_conflict_do_update(
            index_elements=[TrackLinkCache.normalized_key], set_=values
        )
        async with self._session_factory() as session:
            await session.execute(statement)
            await session.commit()
