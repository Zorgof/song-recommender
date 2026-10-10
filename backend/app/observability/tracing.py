"""LangSmith tracing, configured explicitly from Settings.

Every graph run is wrapped in a root run (`recommend_song`) whose id, inputs, metadata and tags
the application sets itself. LangChain and LangGraph runs inside it (nodes, LLM calls) and
`@traceable` catalog calls nest under it automatically.

The client gets the key, endpoint and workspace id from Settings (ADR-01.2); nothing is read
from os.environ. With tracing disabled, `tracing_context(enabled=False)` also switches off any
tracing a developer may have enabled through environment variables.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import langsmith
from langsmith import Client
from langsmith.run_trees import RunTree
from langsmith.schemas import TracerSession

from app.config import Settings

logger = logging.getLogger(__name__)

ROOT_RUN_NAME = "recommend_song"
# Namespace of the run id of the resumed run (after the clarifying question).
_RESUME_NAMESPACE = uuid.UUID("0b6f6a1e-4f4e-4c49-9d43-6b1f1c1a9e57")


def root_run_id(request_id: str, *, resumed: bool) -> uuid.UUID:
    """The first run of a request has the request id; the resumed run a derived, stable id.

    Both are known in advance, so feedback (step 5) can be attached without storing them.
    """
    if not resumed:
        return uuid.UUID(request_id)
    return uuid.uuid5(_RESUME_NAMESPACE, request_id)


def build_client(settings: Settings) -> Client | None:
    if not settings.langsmith_enabled or settings.langsmith_api_key is None:
        return None
    return Client(
        api_key=settings.langsmith_api_key.get_secret_value(),
        api_url=settings.langsmith_endpoint,
        workspace_id=settings.langsmith_workspace_id,
    )


class Tracing:
    def __init__(self, project: str, client: Client | None) -> None:
        self.project = project
        self.client = client
        self._project: TracerSession | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> Tracing:
        return cls(settings.langsmith_project, build_client(settings))

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @asynccontextmanager
    async def root_run(
        self,
        *,
        run_id: uuid.UUID,
        inputs: dict[str, Any],
        metadata: Mapping[str, Any],
        tags: list[str],
    ) -> AsyncIterator[RunTree]:
        """A root run; add metadata/tags and call `end(outputs=...)` before leaving it."""
        with langsmith.tracing_context(
            enabled=self.enabled, client=self.client, project_name=self.project
        ):
            async with langsmith.trace(
                ROOT_RUN_NAME,
                "chain",
                inputs=inputs,
                run_id=run_id,
                metadata=metadata,
                tags=tags,
                client=self.client,
                project_name=self.project,
            ) as run:
                yield run

    async def trace_url(self, run_id: uuid.UUID) -> str | None:
        """UI link of a run. The project is looked up once; failures only cost the link."""
        if self._project is None:
            self._project = await self._read_project()
        if self._project is None or self._project.url is None:
            return None
        return f"{self._project.url}/r/{run_id}?poll=true"

    async def _read_project(self) -> TracerSession | None:
        if self.client is None:
            return None
        try:
            project: TracerSession = await asyncio.to_thread(
                self.client.read_project, project_name=self.project
            )
        except Exception as exc:
            # E.g. the project does not exist until the first trace has been ingested.
            logger.info("LangSmith project not readable yet", extra={"error": type(exc).__name__})
            return None
        return project

    async def flush(self) -> None:
        if self.client is not None:
            await asyncio.to_thread(self.client.flush)
