"""Agent graph end to end, with fake LLMs, a fake catalog and the real SQLite repository."""

from pathlib import Path

import pytest
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select

from app.agents.nodes.music_curator import ESCALATION_NO_VERIFIED
from app.agents.nodes.verify_candidates import REASON_EXCLUDED
from app.agents.runner import Completed, NeedsClarification
from app.agents.state import MAX_CURATION_ATTEMPTS
from app.db.models import InputMode, Recommendation, RecommendationStatus
from app.errors import ConflictError, LLMUnavailableError, NotFoundError
from app.llm.structured import ESCALATION_INVALID_OUTPUT
from tests.agent_fakes import (
    FakeCatalog,
    SessionFactory,
    candidate,
    clarification_profile,
    curator_output,
    make_harness,
    need_profile,
    track,
)

SIMPLE_EN = "I'm tired after a long day at work and want something calm to relax."
SIMPLE_PL = "Jestem zmęczony po długim dniu w pracy i chcę się wyciszyć."
VAGUE = "meh"
COMPLEX = (
    "I got the job but I'm leaving my friends behind, and although I should be happy "
    "I'm not sure what I feel."
)

HOLOCENE = track("Holocene", "Bon Iver", "holocene-id")
RIVER = track("River", "Leon Bridges", "river-id")


def system_prompt(messages: list[BaseMessage]) -> str:
    return str(messages[0].content)


def user_prompt(messages: list[BaseMessage]) -> str:
    return str(messages[1].content)


# --- Happy paths ---


async def test_happy_path_en(tmp_path: Path, session_factory: SessionFactory) -> None:
    catalog = FakeCatalog.knowing(HOLOCENE, RIVER, videos={"bon iver|holocene": "yt-holo"})
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"), ("River", "Leon Bridges"))],
        },
        catalog=catalog,
    )

    outcome = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")

    assert isinstance(outcome, Completed)
    rec = outcome.recommendation
    assert (rec.title, rec.artist) == ("Holocene", "Bon Iver")
    assert rec.spotify_verified and rec.spotify_track_id == "holocene-id"
    assert rec.spotify_url == "https://open.spotify.com/track/holocene-id"
    assert rec.album_art_url == "https://i.scdn.co/image/holocene-id"
    assert rec.youtube_verified and rec.youtube_url == "https://www.youtube.com/watch?v=yt-holo"
    assert rec.explanation == "Holocene will help you slow down."
    assert rec.need_summary == "You are tired after work and want to unwind."
    assert rec.locale == "en"
    assert rec.trace_url is None  # tracing disabled
    # Simple request: light tier only, no router call, one curation attempt.
    assert [schema for schema, _ in h.light.calls] == ["NeedProfile", "CuratorOutput"]
    assert h.heavy.calls == []
    # All candidates are verified concurrently; YouTube only for the chosen song.
    assert sorted(catalog.spotify_lookups) == [("Holocene", "Bon Iver"), ("River", "Leon Bridges")]
    assert catalog.youtube_lookups == [("Holocene", "Bon Iver")]

    row = await h.repository.get(rec.request_id)
    assert row is not None
    assert row.status is RecommendationStatus.COMPLETED
    assert (row.title, row.artist, row.spotify_track_id) == ("Holocene", "Bon Iver", "holocene-id")
    assert row.input_text == SIMPLE_EN
    assert row.need_profile == need_profile()
    assert row.models_used == {"need_analyst": "light-v1", "music_curator": "light-v1"}
    assert row.escalated is False


async def test_happy_path_pl(tmp_path: Path, session_factory: SessionFactory) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile(summary_localized="Jesteś zmęczony i chcesz odpocząć.")],
            "CuratorOutput": [
                curator_output(
                    candidate(1, "Holocene", "Bon Iver", "Ta piosenka pomoże ci zwolnić.")
                )
            ],
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
    )

    outcome = await h.runner.start(SIMPLE_PL, input_mode=InputMode.TEXT, locale="pl")

    assert isinstance(outcome, Completed)
    rec = outcome.recommendation
    assert rec.locale == "pl"
    assert rec.explanation == "Ta piosenka pomoże ci zwolnić."
    assert rec.need_summary == "Jesteś zmęczony i chcesz odpocząć."
    # The UI language is passed to both agents; the user text is passed verbatim.
    analyst_messages = h.light.calls_for("NeedProfile")[0]
    curator_messages = h.light.calls_for("CuratorOutput")[0]
    assert "in Polish" in system_prompt(analyst_messages)
    assert SIMPLE_PL in user_prompt(analyst_messages)
    assert "in Polish" in system_prompt(curator_messages)
    assert "User interface language: Polish." in user_prompt(curator_messages)
    assert "Propose exactly 3 different songs" in system_prompt(curator_messages)


async def test_complex_request_uses_heavy_tier(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={},
        heavy={
            "NeedProfile": [need_profile(goal="release")],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
    )

    outcome = await h.runner.start(COMPLEX, input_mode=InputMode.TEXT, locale="en")

    assert isinstance(outcome, Completed)
    assert h.light.calls == []
    assert [schema for schema, _ in h.heavy.calls] == ["NeedProfile", "CuratorOutput"]
    row = await h.repository.get(outcome.recommendation.request_id)
    assert row is not None and row.escalated is False


async def test_uncertain_request_is_classified_by_the_light_model(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={"RouterClassification": [{"complexity": "complex", "reason": "Mixed feelings."}]},
        heavy={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
    )

    outcome = await h.runner.start("Good day, but strange.", input_mode=InputMode.TEXT, locale="en")

    assert isinstance(outcome, Completed)
    router_messages = h.light.calls_for("RouterClassification")
    assert len(router_messages) == 1
    assert "Good day, but strange." in user_prompt(router_messages[0])
    assert [schema for schema, _ in h.heavy.calls] == ["NeedProfile", "CuratorOutput"]
    row = await h.repository.get(outcome.recommendation.request_id)
    assert row is not None and row.models_used is not None
    assert row.models_used["route_request"] == "light-v1"


# --- Clarification ---


async def test_clarification_path(tmp_path: Path, session_factory: SessionFactory) -> None:
    question = "Jak minął ci dzień?"
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "RouterClassification": [{"complexity": "simple", "reason": "Too short to tell."}],
            "NeedProfile": [clarification_profile(question), need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
    )

    first = await h.runner.start(VAGUE, input_mode=InputMode.TEXT, locale="pl")

    assert isinstance(first, NeedsClarification)
    assert first.question == question
    row = await h.repository.get(first.request_id)
    assert row is not None
    assert row.status is RecommendationStatus.NEEDS_CLARIFICATION
    assert row.clarification_question == question
    assert h.light.calls_for("CuratorOutput") == []

    second = await h.runner.answer(first.request_id, "Długi i męczący, chcę odpocząć.")

    assert isinstance(second, Completed)
    assert second.recommendation.request_id == first.request_id
    assert (second.recommendation.title, second.recommendation.artist) == ("Holocene", "Bon Iver")
    # The analyst ran again with the question, the answer and the instruction not to ask again.
    retry_prompt = user_prompt(h.light.calls_for("NeedProfile")[1])
    assert question in retry_prompt
    assert "Długi i męczący, chcę odpocząć." in retry_prompt
    assert "do not ask another one" in retry_prompt
    # Routing ran only once, before the question.
    assert len(h.light.calls_for("RouterClassification")) == 1
    row = await h.repository.get(first.request_id)
    assert row is not None
    assert row.status is RecommendationStatus.COMPLETED
    assert row.clarification_answer == "Długi i męczący, chcę odpocząć."


async def test_clarifying_question_is_asked_at_most_once(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "RouterClassification": [{"complexity": "simple", "reason": "Short."}],
            # The model keeps asking; the graph proceeds after the first answer anyway.
            "NeedProfile": [clarification_profile("How are you?")],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
    )

    first = await h.runner.start(VAGUE, input_mode=InputMode.TEXT, locale="en")
    assert isinstance(first, NeedsClarification)
    second = await h.runner.answer(first.request_id, "Still meh.")

    assert isinstance(second, Completed)
    assert len(h.light.calls_for("NeedProfile")) == 2


async def test_answer_requires_a_waiting_recommendation(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
    )
    done = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")
    assert isinstance(done, Completed)

    with pytest.raises(NotFoundError):
        await h.runner.answer("00000000-0000-4000-8000-000000000000", "hello")
    with pytest.raises(ConflictError):
        await h.runner.answer(done.recommendation.request_id, "hello")


async def test_clarification_survives_a_restart(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    """The paused graph lives in checkpoints.db, so a new process can resume it."""
    checkpoints = str(tmp_path / "checkpoints.db")
    light = {
        "RouterClassification": [{"complexity": "simple", "reason": "Short."}],
        "NeedProfile": [clarification_profile("How was your day?"), need_profile()],
        "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
    }
    catalog = FakeCatalog.knowing(HOLOCENE)

    async with AsyncSqliteSaver.from_conn_string(checkpoints) as saver:
        before = make_harness(
            tmp_path, session_factory, light=light, catalog=catalog, checkpointer=saver
        )
        first = await before.runner.start(VAGUE, input_mode=InputMode.TEXT, locale="en")
    assert isinstance(first, NeedsClarification)

    async with AsyncSqliteSaver.from_conn_string(checkpoints) as saver:
        after = make_harness(
            tmp_path, session_factory, light=light, catalog=catalog, checkpointer=saver
        )
        # The new process only gets the second NeedProfile answer.
        after.light.responses["NeedProfile"] = [need_profile()]
        second = await after.runner.answer(first.request_id, "Long and tiring.")

    assert isinstance(second, Completed)
    assert second.recommendation.title == "Holocene"


# --- Retries, escalation, fallbacks ---


async def test_retry_with_escalation_to_heavy(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Invented Song", "Nobody"), ("Fake Tune", "Noone"))],
        },
        heavy={"CuratorOutput": [curator_output(("River", "Leon Bridges"))]},
        catalog=FakeCatalog.knowing(RIVER),
    )

    outcome = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")

    assert isinstance(outcome, Completed)
    assert (outcome.recommendation.title, outcome.recommendation.spotify_verified) == (
        "River",
        True,
    )
    assert len(h.light.calls_for("CuratorOutput")) == 1
    retry_prompt = user_prompt(h.heavy.calls_for("CuratorOutput")[0])
    assert "Nobody - Invented Song: not found on Spotify" in retry_prompt
    assert "Noone - Fake Tune: not found on Spotify" in retry_prompt
    row = await h.repository.get(outcome.recommendation.request_id)
    assert row is not None
    assert row.escalated is True
    assert row.models_used == {"need_analyst": "light-v1", "music_curator": "heavy-v1"}


async def test_all_attempts_unverified_fall_back_to_search_links(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    catalog = FakeCatalog()
    h = make_harness(
        tmp_path,
        session_factory,
        light={"NeedProfile": [need_profile()], "CuratorOutput": [curator_output(("A", "B"))]},
        heavy={
            "CuratorOutput": [
                curator_output(("Second Try", "Ghost")),
                curator_output(
                    candidate(1, "Third Try", "Phantom", "Unverified but heartfelt."),
                    candidate(2, "Other", "Phantom"),
                ),
            ]
        },
        catalog=catalog,
    )

    outcome = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")

    assert isinstance(outcome, Completed)
    rec = outcome.recommendation
    assert (rec.title, rec.artist) == ("Third Try", "Phantom")
    assert rec.spotify_verified is False
    assert rec.spotify_track_id is None and rec.album_art_url is None
    assert rec.spotify_url == "https://open.spotify.com/search/Phantom%20Third%20Try"
    assert rec.youtube_verified is False
    assert rec.youtube_url == "https://www.youtube.com/results?search_query=Phantom+Third+Try"
    assert rec.explanation == "Unverified but heartfelt."
    total_attempts = len(h.light.calls_for("CuratorOutput")) + len(
        h.heavy.calls_for("CuratorOutput")
    )
    assert total_attempts == MAX_CURATION_ATTEMPTS
    # The last retry sees every rejection so far.
    last_prompt = user_prompt(h.heavy.calls_for("CuratorOutput")[1])
    assert "B - A:" in last_prompt and "Ghost - Second Try:" in last_prompt


async def test_spotify_unavailable_skips_retries(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"), ("River", "Leon Bridges"))],
        },
        catalog=FakeCatalog(spotify_down=True),
    )

    outcome = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")

    assert isinstance(outcome, Completed)
    assert outcome.recommendation.title == "Holocene"
    assert outcome.recommendation.spotify_verified is False
    assert len(h.light.calls_for("CuratorOutput")) == 1
    assert h.heavy.calls == []


async def test_recently_recommended_songs_are_excluded(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"), ("River", "Leon Bridges"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE, RIVER),
    )
    first = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")
    assert isinstance(first, Completed) and first.recommendation.title == "Holocene"

    second = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")

    assert isinstance(second, Completed)
    assert second.recommendation.title == "River"
    second_prompt = user_prompt(h.light.calls_for("CuratorOutput")[1])
    assert "- Bon Iver - Holocene" in second_prompt
    # The excluded song is rejected without a catalog lookup.
    assert h.catalog.spotify_lookups.count(("Holocene", "Bon Iver")) == 1
    assert REASON_EXCLUDED == "recommended recently"


async def test_exclusion_window_follows_the_setting(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"), ("River", "Leon Bridges"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE, RIVER),
        history_exclude_last_n=0,
    )

    for _ in range(2):
        outcome = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")
        assert isinstance(outcome, Completed) and outcome.recommendation.title == "Holocene"


async def test_invalid_need_profile_escalates_to_heavy(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile(energy=7, goal="party")],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
        },
        heavy={"NeedProfile": [need_profile()]},
        catalog=FakeCatalog.knowing(HOLOCENE),
    )

    outcome = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")

    assert isinstance(outcome, Completed)
    row = await h.repository.get(outcome.recommendation.request_id)
    assert row is not None
    assert row.escalated is True
    assert row.models_used == {"need_analyst": "heavy-v1", "music_curator": "light-v1"}
    assert ESCALATION_INVALID_OUTPUT == "invalid_structured_output"
    assert ESCALATION_NO_VERIFIED == "no_verified_candidates"


async def test_llm_failure_marks_the_recommendation_failed(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path, session_factory, light={"NeedProfile": [RuntimeError("provider down")]}
    )

    with pytest.raises(LLMUnavailableError):
        await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")

    rows = await h.repository.recent_tracks(10)
    assert rows == []
    async with session_factory() as session:
        failed = (await session.scalars(select(Recommendation))).one()
    assert failed.status is RecommendationStatus.FAILED
    assert failed.error_code == "llm_unavailable"


async def test_voice_input_tells_the_analyst_about_the_transcript(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
    )

    await h.runner.start(SIMPLE_EN, input_mode=InputMode.VOICE, locale="en")

    assert "speech transcript" in user_prompt(h.light.calls_for("NeedProfile")[0])
