from datetime import UTC, date, datetime, timedelta

from app.db.models import InputMode, Recommendation, RecommendationStatus, UsageAction
from app.db.repositories import RecommendationRepository, UsageRepository
from tests.agent_fakes import SessionFactory


async def add(
    session_factory: SessionFactory,
    rec_id: str,
    *,
    minutes: int,
    status: RecommendationStatus = RecommendationStatus.COMPLETED,
    title: str | None = "Song",
    visitor_id: str | None = None,
) -> None:
    async with session_factory() as session:
        session.add(
            Recommendation(
                id=rec_id,
                visitor_id=visitor_id,
                created_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC) + timedelta(minutes=minutes),
                status=status,
                locale="en",
                input_mode=InputMode.TEXT,
                input_text="text",
                title=f"{title} {rec_id}" if title else None,
                artist="Artist" if title else None,
            )
        )
        await session.commit()


async def test_recent_tracks_are_completed_ones_newest_first(
    session_factory: SessionFactory,
) -> None:
    repo = RecommendationRepository(session_factory)
    await add(session_factory, "a", minutes=1)
    await add(session_factory, "b", minutes=3)
    await add(session_factory, "c", minutes=2)
    await add(session_factory, "failed", minutes=4, status=RecommendationStatus.FAILED)
    await add(
        session_factory, "pending", minutes=5, status=RecommendationStatus.PENDING, title=None
    )

    assert await repo.recent_tracks(10) == [
        {"title": "Song b", "artist": "Artist"},
        {"title": "Song c", "artist": "Artist"},
        {"title": "Song a", "artist": "Artist"},
    ]
    assert await repo.recent_tracks(1) == [{"title": "Song b", "artist": "Artist"}]
    assert await repo.recent_tracks(0) == []


async def test_status_transitions(session_factory: SessionFactory) -> None:
    repo = RecommendationRepository(session_factory)
    await repo.create("r1", locale="pl", input_mode=InputMode.VOICE, input_text="meh")

    await repo.mark_needs_clarification("r1", question="Jak się czujesz?", need_profile={"x": 1})
    row = await repo.get("r1")
    assert row is not None
    assert (row.status, row.clarification_question, row.need_profile) == (
        RecommendationStatus.NEEDS_CLARIFICATION,
        "Jak się czujesz?",
        {"x": 1},
    )

    await repo.save_clarification_answer("r1", "Dobrze")
    row = await repo.get("r1")
    assert row is not None
    assert (row.status, row.clarification_answer) == (RecommendationStatus.PENDING, "Dobrze")

    await repo.fail("r1", "llm_unavailable")
    row = await repo.get("r1")
    assert row is not None
    assert (row.status, row.error_code) == (RecommendationStatus.FAILED, "llm_unavailable")
    assert await repo.get("missing") is None


async def test_recent_tracks_belong_to_one_visitor(session_factory: SessionFactory) -> None:
    repo = RecommendationRepository(session_factory)
    await add(session_factory, "mine", minutes=1, visitor_id="me")
    await add(session_factory, "theirs", minutes=2, visitor_id="them")
    await add(session_factory, "nobodys", minutes=3)

    assert await repo.recent_tracks(10, visitor_id="me") == [
        {"title": "Song mine", "artist": "Artist"}
    ]
    assert await repo.recent_tracks(10) == [{"title": "Song nobodys", "artist": "Artist"}]


async def test_list_completed_belongs_to_one_visitor(session_factory: SessionFactory) -> None:
    repo = RecommendationRepository(session_factory)
    await add(session_factory, "a", minutes=1, visitor_id="me")
    await add(session_factory, "b", minutes=2, visitor_id="them")
    await add(session_factory, "c", minutes=3, visitor_id="me")

    rows, total = await repo.list_completed("me", limit=10, offset=0)

    assert [row.id for row in rows] == ["c", "a"]
    assert total == 2


async def test_usage_is_counted_up_to_the_limit(session_factory: SessionFactory) -> None:
    usage = UsageRepository(session_factory)
    today, tomorrow = date(2026, 10, 11), date(2026, 10, 12)
    rec, stt = UsageAction.RECOMMENDATION, UsageAction.TRANSCRIPTION

    assert [await usage.try_use("me", rec, day=today, limit=2) for _ in range(3)] == [
        True,
        True,
        False,
    ]
    # Each visitor, action and day has its own counter.
    assert await usage.try_use("them", rec, day=today, limit=2)
    assert await usage.try_use("me", stt, day=today, limit=2)
    assert await usage.try_use("me", rec, day=tomorrow, limit=2)
    # A lower limit (e.g. after a configuration change) applies at once.
    assert not await usage.try_use("me", rec, day=tomorrow, limit=1)
