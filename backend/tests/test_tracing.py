"""LangSmith wiring, checked offline with a client that records runs instead of sending them."""

import uuid
from pathlib import Path
from typing import Any

from langsmith import Client
from langsmith.schemas import TracerSession

from app.agents.runner import Completed, NeedsClarification
from app.config import Settings
from app.db.models import InputMode
from app.observability.tracing import ROOT_RUN_NAME, Tracing, build_client, root_run_id
from tests.agent_fakes import (
    FakeCatalog,
    SessionFactory,
    clarification_profile,
    curator_output,
    make_harness,
    need_profile,
    track,
)
from tests.conftest import make_settings
from tests.fakes import FAKE_LANGSMITH_KEY

HOLOCENE = track("Holocene", "Bon Iver", "holocene-id")
SIMPLE_EN = "I'm tired after a long day at work and want something calm to relax."
PROJECT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


class RecordingClient(Client):
    """Keeps created and updated runs in memory; makes no network calls."""

    def __init__(self) -> None:
        super().__init__(
            api_key=FAKE_LANGSMITH_KEY,
            api_url="https://api.smith.langchain.com",
            auto_batch_tracing=False,
        )
        self.created: dict[str, dict[str, Any]] = {}
        self.project_reads = 0

    def create_run(self, *args: Any, **kwargs: Any) -> None:
        run = {**kwargs}
        self.created[str(run["id"])] = run

    def update_run(self, run_id: Any, **kwargs: Any) -> None:
        self.created.setdefault(str(run_id), {}).update(
            {k: v for k, v in kwargs.items() if v is not None}
        )

    def read_project(self, **_: Any) -> TracerSession:
        self.project_reads += 1
        return TracerSession(
            id=PROJECT_ID,
            name="test-project",
            tenant_id=TENANT_ID,
            start_time="2026-10-10T00:00:00Z",
            reference_dataset_id=None,
            _host_url="https://smith.langchain.com",
        )

    def flush(self, timeout: float | None = None) -> None:
        return None

    def runs_named(self, name: str) -> list[dict[str, Any]]:
        return [run for run in self.created.values() if run.get("name") == name]


def metadata_of(run: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = (run.get("extra") or {}).get("metadata", {})
    return metadata


async def test_root_run_carries_inputs_metadata_tags_and_children(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    client = RecordingClient()
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
        tracing=Tracing("test-project", client),
    )

    outcome = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="pl")

    assert isinstance(outcome, Completed)
    request_id = outcome.recommendation.request_id
    (root,) = client.runs_named(ROOT_RUN_NAME)
    assert str(root["id"]) == request_id
    assert root.get("parent_run_id") is None
    assert root["inputs"] == {"user_input": SIMPLE_EN, "input_mode": "text", "locale": "pl"}
    assert root["outputs"]["status"] == "completed"
    assert root["outputs"]["recommendation"]["title"] == "Holocene"
    metadata = metadata_of(root)
    assert metadata["thread_id"] == request_id
    assert metadata["prompt_versions"] == {
        "router": "v1",
        "need_analyst": "v1",
        "curator": "v1",
    }
    assert metadata["models"] == {"light": "openai:light-model", "heavy": "openai:heavy-model"}
    assert metadata["candidate_count"] == 3
    assert metadata["routing_complexity"] == "simple"
    assert metadata["routing_source"] == "heuristics"
    assert metadata["models_used"] == {"need_analyst": "light-v1", "music_curator": "light-v1"}
    assert metadata["spotify_verified"] is True
    assert {"text", "locale:pl"} <= set(root["tags"])
    assert "escalated" not in root["tags"]

    # Graph nodes, LLM calls (with the rendered prompts) and catalog lookups are in the trace.
    names = {run.get("name") for run in client.created.values()}
    assert {
        "route_request",
        "need_analyst",
        "music_curator",
        "verify_candidates",
        "finalize",
        "spotify_lookup",
        "youtube_lookup",
    } <= names
    llm_runs = [run for run in client.created.values() if run.get("run_type") == "llm"]
    assert len(llm_runs) == 2
    assert any(SIMPLE_EN in str(run["inputs"]) for run in llm_runs)
    trace_ids = {str(run.get("trace_id")) for run in client.created.values()}
    assert trace_ids == {request_id}

    assert outcome.recommendation.trace_url == (
        f"https://smith.langchain.com/o/{TENANT_ID}/projects/p/{PROJECT_ID}"
        f"/r/{request_id}?poll=true"
    )


async def test_clarification_runs_form_one_thread(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    client = RecordingClient()
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "RouterClassification": [{"complexity": "simple", "reason": "Short."}],
            "NeedProfile": [clarification_profile("How was your day?"), need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
        tracing=Tracing("test-project", client),
    )

    first = await h.runner.start("meh", input_mode=InputMode.VOICE, locale="en", transcript="meh")
    assert isinstance(first, NeedsClarification)
    second = await h.runner.answer(first.request_id, "Long day.")
    assert isinstance(second, Completed)

    roots = {str(run["id"]): run for run in client.runs_named(ROOT_RUN_NAME)}
    resumed_id = str(root_run_id(first.request_id, resumed=True))
    assert set(roots) == {first.request_id, resumed_id}
    asked, resumed = roots[first.request_id], roots[resumed_id]
    assert asked["inputs"]["transcript"] == "meh"
    assert asked["outputs"] == {"status": "needs_clarification", "question": "How was your day?"}
    assert {"voice", "clarified"} <= set(asked["tags"])
    assert resumed["inputs"]["clarification_question"] == "How was your day?"
    assert resumed["inputs"]["clarification_answer"] == "Long day."
    assert "clarified" in resumed["tags"]
    assert metadata_of(asked)["thread_id"] == metadata_of(resumed)["thread_id"] == first.request_id
    assert metadata_of(resumed)["resumed"] is True
    # The link points at the run that produced the recommendation.
    assert second.recommendation.trace_url is not None
    assert resumed_id in second.recommendation.trace_url
    assert client.project_reads == 1


async def test_escalation_is_tagged(tmp_path: Path, session_factory: SessionFactory) -> None:
    client = RecordingClient()
    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Invented", "Nobody"))],
        },
        heavy={"CuratorOutput": [curator_output(("Holocene", "Bon Iver"))]},
        catalog=FakeCatalog.knowing(HOLOCENE),
        tracing=Tracing("test-project", client),
    )

    outcome = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")

    assert isinstance(outcome, Completed)
    (root,) = client.runs_named(ROOT_RUN_NAME)
    assert "escalated" in root["tags"]
    assert metadata_of(root)["escalations"] == [
        {
            "node": "music_curator",
            "from_tier": "light",
            "to_tier": "heavy",
            "reason": "no_verified_candidates",
        }
    ]
    assert metadata_of(root)["curation_attempts"] == 2


async def test_unreadable_project_only_costs_the_link(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    class NoProjectClient(RecordingClient):
        def read_project(self, **_: Any) -> TracerSession:
            raise RuntimeError("project not found")

    h = make_harness(
        tmp_path,
        session_factory,
        light={
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
        tracing=Tracing("test-project", NoProjectClient()),
    )

    outcome = await h.runner.start(SIMPLE_EN, input_mode=InputMode.TEXT, locale="en")

    assert isinstance(outcome, Completed)
    assert outcome.recommendation.trace_url is None


def test_root_run_ids_are_stable() -> None:
    request_id = str(uuid.uuid4())

    assert root_run_id(request_id, resumed=False) == uuid.UUID(request_id)
    assert root_run_id(request_id, resumed=True) == root_run_id(request_id, resumed=True)
    assert root_run_id(request_id, resumed=True) != uuid.UUID(request_id)


def test_client_is_built_only_when_tracing_is_enabled(tmp_path: Path) -> None:
    enabled = make_settings(
        tmp_path,
        langsmith_tracing=True,
        langsmith_api_key=FAKE_LANGSMITH_KEY,
        langsmith_workspace_id="33333333-3333-4333-8333-333333333333",
    )
    no_key = make_settings(tmp_path, langsmith_tracing=True)
    switched_off = make_settings(tmp_path, langsmith_api_key=FAKE_LANGSMITH_KEY)

    client = build_client(enabled)

    assert isinstance(client, Client)
    assert client.api_url == "https://api.smith.langchain.com"
    assert build_client(no_key) is None
    assert build_client(switched_off) is None
    assert Tracing.from_settings(Settings(_env_file=None, data_dir=tmp_path)).enabled is False
