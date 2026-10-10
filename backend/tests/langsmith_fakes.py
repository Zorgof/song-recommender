"""A LangSmith client that records runs and feedback in memory instead of sending them."""

import uuid
from typing import Any

from langsmith import Client
from langsmith.schemas import TracerSession

from tests.fakes import FAKE_LANGSMITH_KEY

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
        self.feedback_created: list[dict[str, Any]] = []
        self.feedback_updated: list[dict[str, Any]] = []
        # Set to make feedback calls fail, as when LangSmith is unreachable.
        self.fail_feedback = False

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

    def create_feedback(self, *args: Any, **kwargs: Any) -> Any:
        if self.fail_feedback:
            raise RuntimeError("LangSmith is down")
        self.feedback_created.append(kwargs)
        return None

    def update_feedback(self, feedback_id: Any, **kwargs: Any) -> None:
        if self.fail_feedback:
            raise RuntimeError("LangSmith is down")
        self.feedback_updated.append({"feedback_id": feedback_id, **kwargs})

    def runs_named(self, name: str) -> list[dict[str, Any]]:
        return [run for run in self.created.values() if run.get("name") == name]
