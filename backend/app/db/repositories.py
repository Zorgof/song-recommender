"""Repository of the `recommendations` table.

It takes a session factory rather than a request session: the agent graph writes results
outside FastAPI's dependency injection.
"""

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import InputMode, Recommendation, RecommendationStatus


class RecommendationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self, request_id: str, *, locale: str, input_mode: InputMode, input_text: str
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                Recommendation(
                    id=request_id, locale=locale, input_mode=input_mode, input_text=input_text
                )
            )
            await session.commit()

    async def get(self, request_id: str) -> Recommendation | None:
        async with self._session_factory() as session:
            return await session.get(Recommendation, request_id)

    async def mark_needs_clarification(
        self, request_id: str, *, question: str, need_profile: dict[str, Any] | None
    ) -> None:
        await self._update(
            request_id,
            status=RecommendationStatus.NEEDS_CLARIFICATION,
            clarification_question=question,
            need_profile=need_profile,
        )

    async def save_clarification_answer(self, request_id: str, answer: str) -> None:
        await self._update(
            request_id, status=RecommendationStatus.PENDING, clarification_answer=answer
        )

    async def complete(
        self,
        request_id: str,
        *,
        title: str,
        artist: str,
        album_art_url: str | None,
        spotify_track_id: str | None,
        spotify_url: str,
        spotify_verified: bool,
        youtube_url: str,
        youtube_verified: bool,
        explanation: str,
        need_summary: str,
        need_profile: dict[str, Any],
        models_used: dict[str, Any],
        escalated: bool,
    ) -> None:
        await self._update(
            request_id,
            status=RecommendationStatus.COMPLETED,
            title=title,
            artist=artist,
            album_art_url=album_art_url,
            spotify_track_id=spotify_track_id,
            spotify_url=spotify_url,
            spotify_verified=spotify_verified,
            youtube_url=youtube_url,
            youtube_verified=youtube_verified,
            explanation=explanation,
            need_summary=need_summary,
            need_profile=need_profile,
            models_used=models_used,
            escalated=escalated,
            error_code=None,
        )

    async def fail(self, request_id: str, error_code: str) -> None:
        await self._update(request_id, status=RecommendationStatus.FAILED, error_code=error_code)

    async def recent_tracks(self, limit: int) -> list[dict[str, str]]:
        """Title and artist of the last `limit` completed recommendations, newest first."""
        if limit <= 0:
            return []
        statement = (
            select(Recommendation.title, Recommendation.artist)
            .where(
                Recommendation.status == RecommendationStatus.COMPLETED,
                Recommendation.title.is_not(None),
                Recommendation.artist.is_not(None),
            )
            .order_by(Recommendation.created_at.desc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return [{"title": str(title), "artist": str(artist)} for title, artist in rows]

    async def _update(self, request_id: str, **values: Any) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(Recommendation).where(Recommendation.id == request_id).values(**values)
            )
            await session.commit()
