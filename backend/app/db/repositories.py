"""Repositories of the `recommendations`, `feedback` and `daily_usage` tables.

They take a session factory rather than a request session: the agent graph writes results
outside FastAPI's dependency injection.
"""

from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.base import utc_now
from app.db.models import (
    DailyUsage,
    Feedback,
    InputMode,
    Recommendation,
    RecommendationStatus,
    UsageAction,
)


class RecommendationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        request_id: str,
        *,
        locale: str,
        input_mode: InputMode,
        input_text: str,
        visitor_id: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                Recommendation(
                    id=request_id,
                    visitor_id=visitor_id,
                    locale=locale,
                    input_mode=input_mode,
                    input_text=input_text,
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

    async def recent_tracks(
        self, limit: int, *, visitor_id: str | None = None
    ) -> list[dict[str, str]]:
        """Title and artist of the visitor's last `limit` completed recommendations, newest
        first. `visitor_id=None` selects the requests made without a visitor."""
        if limit <= 0:
            return []
        statement = (
            select(Recommendation.title, Recommendation.artist)
            .where(
                Recommendation.visitor_id == visitor_id,
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

    async def list_completed(
        self, visitor_id: str, *, limit: int, offset: int
    ) -> tuple[list[Recommendation], int]:
        """A page of the visitor's completed recommendations, newest first, with their
        feedback; and the total number of the visitor's completed recommendations."""
        completed = (Recommendation.visitor_id == visitor_id) & (
            Recommendation.status == RecommendationStatus.COMPLETED
        )
        page = (
            select(Recommendation)
            .where(completed)
            .options(selectinload(Recommendation.feedback))
            .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(page)).all())
            total = await session.scalar(
                select(func.count()).select_from(Recommendation).where(completed)
            )
        return rows, total or 0

    async def _update(self, request_id: str, **values: Any) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(Recommendation).where(Recommendation.id == request_id).values(**values)
            )
            await session.commit()


class FeedbackRepository:
    """One rating per recommendation: rating again replaces score and comment."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, recommendation_id: str) -> Feedback | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(Feedback).where(Feedback.recommendation_id == recommendation_id)
            )

    async def save(self, recommendation_id: str, *, score: int, comment: str | None) -> None:
        """Insert or replace the rating. It is not synced to LangSmith until mark_synced()."""
        values = {"score": score, "comment": comment, "synced_to_langsmith": False}
        statement = (
            insert(Feedback)
            .values(recommendation_id=recommendation_id, created_at=utc_now(), **values)
            .on_conflict_do_update(index_elements=[Feedback.recommendation_id], set_=values)
        )
        async with self._session_factory() as session:
            await session.execute(statement)
            await session.commit()

    async def mark_synced(self, recommendation_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(Feedback)
                .where(Feedback.recommendation_id == recommendation_id)
                .values(synced_to_langsmith=True)
            )
            await session.commit()


class UsageRepository:
    """Per-visitor, per-day counters of limited actions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def try_use(self, visitor_id: str, action: UsageAction, *, day: date, limit: int) -> bool:
        """Count one use if fewer than `limit` were counted that day; False when none is left.

        One upsert statement checks and counts, so concurrent requests cannot both take the
        last use.
        """
        statement = (
            insert(DailyUsage)
            .values(visitor_id=visitor_id, day=day, action=action, used=1)
            .on_conflict_do_update(
                index_elements=[DailyUsage.visitor_id, DailyUsage.day, DailyUsage.action],
                set_={"used": DailyUsage.used + 1},
                where=DailyUsage.used < limit,
            )
            .returning(DailyUsage.used)
        )
        async with self._session_factory() as session:
            used = (await session.execute(statement)).scalar_one_or_none()
            await session.commit()
        return used is not None
