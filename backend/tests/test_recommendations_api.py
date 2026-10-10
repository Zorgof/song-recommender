"""Recommendation API end to end: real app, routers, runner and graph; fake LLMs and catalog."""

from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from anyio.from_thread import BlockingPortal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Feedback, Recommendation, RecommendationStatus
from app.observability.tracing import FEEDBACK_KEY, Tracing, feedback_id, root_run_id
from tests.agent_fakes import (
    FakeCatalog,
    Harness,
    clarification_profile,
    curator_output,
    make_harness,
    need_profile,
    track,
)
from tests.langsmith_fakes import PROJECT_ID, RecordingClient

SIMPLE_EN = "I'm tired after a long day at work and want something calm to relax."
SONGS = [("Holocene", "Bon Iver"), ("River", "Leon Bridges"), ("Weightless", "Marconi Union")]
CATALOG_TRACKS = [track(title, artist) for title, artist in SONGS]

# One curator answer per request, each with a different song (recent songs are excluded).
SCRIPT: dict[str, list[Any]] = {
    "RouterClassification": [{"complexity": "simple", "reason": "Short."}],
    "NeedProfile": [need_profile()],
    "CuratorOutput": [curator_output(song) for song in SONGS],
}

UseHarness = Callable[..., Harness]


@pytest.fixture
def api(app: FastAPI, tmp_path: Path) -> Iterator[tuple[TestClient, UseHarness]]:
    """The real app; `use(...)` swaps in a runner with fake LLMs and catalog (and tracing)."""
    with TestClient(app) as client:

        def use(light: dict[str, list[Any]] | None = None, **kwargs: Any) -> Harness:
            tracing = kwargs.setdefault("tracing", Tracing("test-project", None))
            kwargs.setdefault("catalog", FakeCatalog.knowing(*CATALOG_TRACKS))
            harness = make_harness(
                tmp_path, app.state.session_factory, light=light or SCRIPT, **kwargs
            )
            app.state.recommender = harness.runner
            app.state.tracing = tracing
            return harness

        yield client, use


def recommend(client: TestClient, text: str = SIMPLE_EN, locale: str = "en") -> Any:
    response = client.post(
        "/api/recommendations", json={"text": text, "input_mode": "text", "locale": locale}
    )
    assert response.status_code == 200, response.text
    return response.json()


def db_row(app: FastAPI, request_id: str) -> Recommendation:
    async def load() -> Recommendation:
        async with app.state.session_factory() as session:
            row: Recommendation = await session.get_one(Recommendation, request_id)
            return row

    return _run(app, load)


def feedback_rows(app: FastAPI) -> list[Feedback]:
    async def load() -> list[Feedback]:
        async with app.state.session_factory() as session:
            return list((await session.scalars(select(Feedback))).all())

    return _run(app, load)


def _run[T](app: FastAPI, load: Callable[[], Awaitable[T]]) -> T:
    # The database engine belongs to the TestClient's event loop; query it there.
    portal: BlockingPortal = app.state.portal
    return portal.call(load)


@pytest.fixture(autouse=True)
def expose_portal(api: tuple[TestClient, UseHarness], app: FastAPI) -> None:
    client, _ = api
    assert client.portal is not None
    app.state.portal = client.portal


# --- POST /api/recommendations ---


def test_completed_recommendation(api: tuple[TestClient, UseHarness], app: FastAPI) -> None:
    client, use = api
    use()

    body = recommend(client)

    assert body["status"] == "completed"
    rec = body["recommendation"]
    assert (rec["title"], rec["artist"], rec["locale"]) == ("Holocene", "Bon Iver", "en")
    assert rec["spotify_verified"] is True
    assert rec["spotify_track_id"] == CATALOG_TRACKS[0].id
    assert rec["youtube_url"].startswith("https://www.youtube.com/results?")
    assert rec["youtube_verified"] is False
    assert rec["explanation"] == "Holocene will help you slow down."
    assert rec["need_summary"] == "You are tired after work and want to unwind."
    assert rec["trace_url"] is None
    assert db_row(app, rec["request_id"]).status is RecommendationStatus.COMPLETED


def test_clarification_round_trip(api: tuple[TestClient, UseHarness], app: FastAPI) -> None:
    client, use = api
    use({**SCRIPT, "NeedProfile": [clarification_profile("Jak minął ci dzień?"), need_profile()]})

    first = recommend(client, text="hmm", locale="pl")

    assert first == {
        "status": "needs_clarification",
        "request_id": first["request_id"],
        "question": "Jak minął ci dzień?",
    }
    response = client.post(
        f"/api/recommendations/{first['request_id']}/clarification",
        json={"answer": "  Długi i męczący.  "},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["recommendation"]["request_id"] == first["request_id"]
    row = db_row(app, first["request_id"])
    assert row.clarification_answer == "Długi i męczący."  # trimmed
    assert row.status is RecommendationStatus.COMPLETED


def test_text_is_trimmed_before_it_is_used(
    api: tuple[TestClient, UseHarness], app: FastAPI
) -> None:
    client, use = api
    harness = use()

    body = recommend(client, text=f"   {SIMPLE_EN}\n ")

    assert db_row(app, body["recommendation"]["request_id"]).input_text == SIMPLE_EN
    analyst_prompt = str(harness.light.calls_for("NeedProfile")[0][1].content)
    assert f"<user_description>\n{SIMPLE_EN}\n</user_description>" in analyst_prompt


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "  a  ", "locale": "en"},  # under 3 characters after trimming
        {"text": "x" * 2001, "locale": "en"},
        {"text": SIMPLE_EN, "locale": "de"},
        {"text": SIMPLE_EN},
        {"text": SIMPLE_EN, "locale": "en", "input_mode": "telepathy"},
        {"text": SIMPLE_EN, "locale": "en", "unexpected": True},
    ],
    ids=["too-short", "too-long", "bad-locale", "no-locale", "bad-mode", "extra-field"],
)
def test_invalid_requests(api: tuple[TestClient, UseHarness], payload: dict[str, Any]) -> None:
    client, use = api
    harness = use()

    response = client.post("/api/recommendations", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert harness.light.calls == []


def test_llm_failure_returns_the_error_shape(
    api: tuple[TestClient, UseHarness], app: FastAPI
) -> None:
    client, use = api
    use({"NeedProfile": [RuntimeError("provider down")]})

    response = client.post(
        "/api/recommendations", json={"text": SIMPLE_EN, "input_mode": "voice", "locale": "en"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_unavailable"


# --- POST /api/recommendations/{id}/clarification ---


def test_clarification_errors(api: tuple[TestClient, UseHarness]) -> None:
    client, use = api
    use()
    completed = recommend(client)["recommendation"]["request_id"]

    unknown = client.post("/api/recommendations/nope/clarification", json={"answer": "x"})
    not_waiting = client.post(
        f"/api/recommendations/{completed}/clarification", json={"answer": "x"}
    )
    empty = client.post(f"/api/recommendations/{completed}/clarification", json={"answer": " "})

    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "not_found")
    assert (not_waiting.status_code, not_waiting.json()["error"]["code"]) == (409, "conflict")
    assert (empty.status_code, empty.json()["error"]["code"]) == (422, "validation_error")


def test_answer_without_a_checkpoint_fails_cleanly(
    api: tuple[TestClient, UseHarness], app: FastAPI
) -> None:
    client, use = api
    use({**SCRIPT, "NeedProfile": [clarification_profile("How are you?")]})
    request_id = recommend(client, text="hmm")["request_id"]
    use()  # a new runner with an empty checkpointer, as after deleting checkpoints.db

    response = client.post(
        f"/api/recommendations/{request_id}/clarification", json={"answer": "Fine."}
    )

    assert (response.status_code, response.json()["error"]["code"]) == (409, "conflict")
    row = db_row(app, request_id)
    assert (row.status, row.error_code) == (RecommendationStatus.FAILED, "conflict")


# --- GET /api/recommendations ---


def test_history_pages_newest_first(api: tuple[TestClient, UseHarness]) -> None:
    client, use = api
    use()
    ids = [recommend(client)["recommendation"]["request_id"] for _ in SONGS]
    use({**SCRIPT, "NeedProfile": [clarification_profile("How are you?")]})
    recommend(client, text="hmm")  # waiting for an answer: not in the history

    first = client.get("/api/recommendations", params={"limit": 2}).json()
    second = client.get("/api/recommendations", params={"limit": 2, "offset": 2}).json()

    assert (first["total"], first["limit"], first["offset"]) == (3, 2, 0)
    assert [item["request_id"] for item in first["items"]] == [ids[2], ids[1]]
    assert [item["request_id"] for item in second["items"]] == [ids[0]]
    item = second["items"][0]
    assert (item["title"], item["artist"], item["input_text"]) == (
        "Holocene",
        "Bon Iver",
        SIMPLE_EN,
    )
    assert item["feedback"] is None
    assert item["trace_url"] is None
    assert [item["title"] for item in first["items"]] == ["Weightless", "River"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_history_paging_is_validated(
    api: tuple[TestClient, UseHarness], params: dict[str, int]
) -> None:
    client, use = api
    use()

    response = client.get("/api/recommendations", params=params)

    assert response.status_code == 422


def test_history_shows_trace_links_when_tracing_is_on(api: tuple[TestClient, UseHarness]) -> None:
    client, use = api
    use(tracing=Tracing("test-project", RecordingClient()))
    request_id = recommend(client)["recommendation"]["request_id"]

    (item,) = client.get("/api/recommendations").json()["items"]

    assert item["trace_url"].endswith(f"/projects/p/{PROJECT_ID}/r/{request_id}?poll=true")


# --- POST /api/recommendations/{id}/feedback ---


def test_feedback_is_stored_and_sent_to_langsmith(
    api: tuple[TestClient, UseHarness], app: FastAPI
) -> None:
    client, use = api
    langsmith = RecordingClient()
    use(tracing=Tracing("test-project", langsmith))
    request_id = recommend(client)["recommendation"]["request_id"]

    response = client.post(
        f"/api/recommendations/{request_id}/feedback", json={"score": "up", "comment": " Great "}
    )

    assert response.status_code == 204
    assert response.content == b""
    (row,) = feedback_rows(app)
    assert (row.score, row.comment, row.synced_to_langsmith) == (1, "Great", True)
    (sent,) = langsmith.feedback_created
    assert sent["run_id"] == root_run_id(request_id, resumed=False)
    assert sent["key"] == FEEDBACK_KEY
    assert (sent["score"], sent["comment"]) == (1, "Great")
    assert sent["feedback_id"] == feedback_id(request_id)
    assert sent["session_id"] == PROJECT_ID


def test_rating_again_replaces_the_rating(api: tuple[TestClient, UseHarness], app: FastAPI) -> None:
    client, use = api
    langsmith = RecordingClient()
    use(tracing=Tracing("test-project", langsmith))
    request_id = recommend(client)["recommendation"]["request_id"]
    url = f"/api/recommendations/{request_id}/feedback"

    client.post(url, json={"score": "up"})
    langsmith.create_feedback = _raise_conflict  # type: ignore[method-assign]
    client.post(url, json={"score": "down", "comment": "Too slow."})

    (row,) = feedback_rows(app)
    assert (row.score, row.comment, row.synced_to_langsmith) == (0, "Too slow.", True)
    # The second rating could not be created again, so it updated the same LangSmith feedback.
    (updated,) = langsmith.feedback_updated
    assert updated == {
        "feedback_id": feedback_id(request_id),
        "score": 0,
        "comment": "Too slow.",
    }
    (item,) = client.get("/api/recommendations").json()["items"]
    assert item["feedback"] == {
        "score": "down",
        "comment": "Too slow.",
        "synced_to_langsmith": True,
    }


def _raise_conflict(*_: Any, **__: Any) -> None:
    raise RuntimeError("409 Conflict: feedback already exists")


def test_feedback_is_kept_when_langsmith_fails(
    api: tuple[TestClient, UseHarness], app: FastAPI
) -> None:
    client, use = api
    langsmith = RecordingClient()
    langsmith.fail_feedback = True
    use(tracing=Tracing("test-project", langsmith))
    request_id = recommend(client)["recommendation"]["request_id"]

    response = client.post(f"/api/recommendations/{request_id}/feedback", json={"score": "down"})

    assert response.status_code == 204
    (row,) = feedback_rows(app)
    assert (row.score, row.synced_to_langsmith) == (0, False)


def test_feedback_without_tracing_is_stored_unsynced(
    api: tuple[TestClient, UseHarness], app: FastAPI
) -> None:
    client, use = api
    use()
    request_id = recommend(client)["recommendation"]["request_id"]

    response = client.post(f"/api/recommendations/{request_id}/feedback", json={"score": "up"})

    assert response.status_code == 204
    (row,) = feedback_rows(app)
    assert (row.score, row.synced_to_langsmith) == (1, False)


def test_feedback_on_a_clarified_recommendation_targets_the_resumed_run(
    api: tuple[TestClient, UseHarness],
) -> None:
    client, use = api
    langsmith = RecordingClient()
    use(
        {**SCRIPT, "NeedProfile": [clarification_profile("How are you?"), need_profile()]},
        tracing=Tracing("test-project", langsmith),
    )
    request_id = recommend(client, text="hmm")["request_id"]
    client.post(f"/api/recommendations/{request_id}/clarification", json={"answer": "Tired."})

    client.post(f"/api/recommendations/{request_id}/feedback", json={"score": "up"})

    (sent,) = langsmith.feedback_created
    assert sent["run_id"] == root_run_id(request_id, resumed=True)


def test_feedback_errors(api: tuple[TestClient, UseHarness]) -> None:
    client, use = api
    use({**SCRIPT, "NeedProfile": [clarification_profile("How are you?")]})
    waiting = recommend(client, text="hmm")["request_id"]

    unknown = client.post("/api/recommendations/nope/feedback", json={"score": "up"})
    not_completed = client.post(f"/api/recommendations/{waiting}/feedback", json={"score": "up"})
    bad_score = client.post(f"/api/recommendations/{waiting}/feedback", json={"score": 5})
    long_comment = client.post(
        f"/api/recommendations/{waiting}/feedback", json={"score": "up", "comment": "x" * 1001}
    )

    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "not_found")
    assert (not_completed.status_code, not_completed.json()["error"]["code"]) == (409, "conflict")
    assert bad_score.status_code == 422
    assert long_comment.status_code == 422
