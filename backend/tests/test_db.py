from datetime import UTC, datetime, timedelta, timezone

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.base import Base
from app.db.migrate import upgrade_to_head
from app.db.models import Feedback, InputMode, Recommendation, RecommendationStatus

SessionFactory = async_sessionmaker[AsyncSession]


def make_recommendation(id_: str = "rec-1", **overrides: object) -> Recommendation:
    values: dict[str, object] = {
        "id": id_,
        "locale": "pl",
        "input_mode": InputMode.TEXT,
        "input_text": "Tired after a long day, want something calm.",
        **overrides,
    }
    return Recommendation(**values)


def test_migrations_match_models(settings: Settings) -> None:
    upgrade_to_head(settings.database_path)
    engine = create_engine(f"sqlite:///{settings.database_path}")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()

    assert diff == []


async def test_defaults_on_insert(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        session.add(make_recommendation())
        await session.commit()

    async with session_factory() as session:
        rec = await session.get_one(Recommendation, "rec-1")

    assert rec.status is RecommendationStatus.PENDING
    assert rec.spotify_verified is False
    assert rec.escalated is False
    assert rec.created_at.tzinfo is UTC


async def test_datetimes_round_trip_as_aware_utc(session_factory: SessionFactory) -> None:
    warsaw_summer = timezone(timedelta(hours=2))
    created = datetime(2026, 7, 1, 12, 0, tzinfo=warsaw_summer)
    async with session_factory() as session:
        session.add(make_recommendation(created_at=created))
        await session.commit()

    async with session_factory() as session:
        rec = await session.get_one(Recommendation, "rec-1")

    assert rec.created_at == created
    assert rec.created_at.tzinfo is UTC
    assert rec.created_at.hour == 10


async def test_naive_datetimes_are_rejected(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        session.add(make_recommendation(created_at=datetime(2026, 7, 1, 12, 0)))
        with pytest.raises(StatementError, match="timezone-aware"):
            await session.commit()


async def test_json_columns(session_factory: SessionFactory) -> None:
    profile = {"emotions": ["tired", "hopeful"], "energy": 0.3}
    async with session_factory() as session:
        session.add(make_recommendation(need_profile=profile, models_used={"light": "openai:x"}))
        await session.commit()

    async with session_factory() as session:
        rec = await session.get_one(Recommendation, "rec-1")

    assert rec.need_profile == profile
    assert rec.models_used == {"light": "openai:x"}


async def test_foreign_keys_are_enforced(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        session.add(Feedback(recommendation_id="missing", score=1))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_deleting_recommendation_cascades_to_feedback(
    session_factory: SessionFactory,
) -> None:
    async with session_factory() as session:
        session.add(make_recommendation())
        session.add(Feedback(recommendation_id="rec-1", score=1, comment="great"))
        await session.commit()

    async with session_factory() as session:
        # Raw SQL, so this checks the database-level ON DELETE CASCADE, not the ORM cascade.
        await session.execute(text("DELETE FROM recommendations WHERE id = 'rec-1'"))
        await session.commit()
        remaining = (await session.scalars(select(Feedback))).all()

    assert remaining == []


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO recommendations (id, created_at, status, locale, input_mode, input_text, "
        "spotify_verified, youtube_verified, escalated) "
        "VALUES ('x', '2026-01-01', 'bogus', 'en', 'text', 't', 0, 0, 0)",
        "INSERT INTO recommendations (id, created_at, status, locale, input_mode, input_text, "
        "spotify_verified, youtube_verified, escalated) "
        "VALUES ('x', '2026-01-01', 'pending', 'en', 'telepathy', 't', 0, 0, 0)",
    ],
    ids=["status", "input_mode"],
)
async def test_enum_check_constraints(session_factory: SessionFactory, statement: str) -> None:
    async with session_factory() as session:
        with pytest.raises(IntegrityError, match="CHECK constraint failed"):
            await session.execute(text(statement))


async def test_feedback_score_must_be_binary(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        session.add(make_recommendation())
        session.add(Feedback(recommendation_id="rec-1", score=5))
        with pytest.raises(IntegrityError, match="CHECK constraint failed"):
            await session.commit()
