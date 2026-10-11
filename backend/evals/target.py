"""The system under evaluation: the real agent graph, run for one dataset example.

Differences from the API path (RecommendationRunner), all on purpose:
- No exclusion list. In the app, recently recommended songs are excluded (FR-16). Here every
  example starts without history, so the diversity metric measures the curator's own
  tendency to repeat songs, independent of the order the examples run in.
- A clarifying question is answered automatically, with the example's `clarification_answer`
  or a generic answer, and the run is resumed: every example ends in a recommendation.
- Application errors (LLM or catalog unavailable, invalid output) are returned as
  `status: "failed"` with the error code, so they count against the metrics instead of
  aborting the experiment.
- State lives in a separate database (`evals/.data/eval.db`, which also caches catalog
  lookups between runs) and an in-memory checkpointer; the app's history is not touched.
- The graph runs inside the experiment's target run, so the LLM calls, prompts and catalog
  lookups of every example are traced in the experiment, not in the app's project.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.graph import RecommendationGraph, build_graph
from app.agents.prompt_loader import PromptLibrary
from app.agents.state import AgentDeps, GraphState
from app.config import Settings
from app.db.migrate import upgrade_to_head_async
from app.db.models import InputMode
from app.db.repositories import RecommendationRepository
from app.db.session import create_engine, create_session_factory
from app.errors import AppError
from app.llm.models import ModelRegistry
from app.music.cache import TrackLinkCacheRepository
from app.music.service import build_music_catalog

logger = logging.getLogger(__name__)

EVAL_DATA_DIR = Path(__file__).with_name(".data")

# Used when an example has no scripted answer but the agents ask anyway.
DEFAULT_ANSWERS = {
    "en": "I have nothing to add, please just pick something that fits.",
    "pl": "Nie mam nic do dodania, po prostu wybierz coś pasującego.",
}


class EvalTarget:
    def __init__(
        self, graph: RecommendationGraph, deps: AgentDeps, *, with_youtube: bool = False
    ) -> None:
        self._graph = graph
        self._deps = deps
        self._with_youtube = with_youtube

    async def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """The experiment target: one example in, the run's outputs out."""
        text: str = inputs["text"]
        locale = inputs["locale"]
        input_mode = InputMode(inputs.get("input_mode", "text"))
        request_id = str(uuid.uuid4())
        await self._deps.repository.create(
            request_id, locale=locale, input_mode=input_mode, input_text=text
        )
        state: GraphState = {
            "request_id": request_id,
            "locale": locale,
            "user_input": text,
            "input_mode": input_mode.value,
            "excluded_tracks": [],
        }
        config: RunnableConfig = {"configurable": {"thread_id": request_id}}
        outputs: dict[str, Any] = {
            "request_id": request_id,
            "clarified": False,
            # Without YouTube every link is a search URL; youtube_verified is then not scored.
            "youtube_checked": self._with_youtube,
        }
        started = time.perf_counter()
        try:
            result: dict[str, Any] = await self._graph.ainvoke(state, config, context=self._deps)
            if interrupts := result.get("__interrupt__"):
                question = str(interrupts[0].value["question"])
                answer = inputs.get("clarification_answer") or DEFAULT_ANSWERS[locale]
                outputs |= {
                    "clarified": True,
                    "clarification_question": question,
                    "clarification_answer": answer,
                }
                result = await self._graph.ainvoke(
                    Command(resume=answer), config, context=self._deps
                )
        except AppError as exc:
            logger.warning("Example failed", extra={"error_code": exc.code})
            return outputs | {
                "status": "failed",
                "error_code": exc.code,
                "latency_s": round(time.perf_counter() - started, 2),
            }
        escalations = result.get("escalations") or []
        return outputs | {
            "status": "completed",
            "latency_s": round(time.perf_counter() - started, 2),
            "recommendation": result["recommendation"],
            "need_profile": result.get("need_profile"),
            "routing": result.get("routing"),
            "escalations": escalations,
            "escalated": bool(escalations),
            "curation_attempts": result.get("curation_attempts", 0),
            "models_used": result.get("models_used", {}),
        }


@asynccontextmanager
async def open_eval_target(
    settings: Settings, *, with_youtube: bool, data_dir: Path = EVAL_DATA_DIR
) -> AsyncIterator[EvalTarget]:
    """The real dependencies (models, Spotify, prompts) around a separate database.

    Without `with_youtube` no YouTube API calls are made (links become search URLs): its free
    quota is about 100 searches a day, and the metrics do not depend on YouTube.
    """
    if not with_youtube:
        settings = settings.model_copy(update={"youtube_api_key": None})
    database_path = data_dir / "eval.db"
    await upgrade_to_head_async(database_path)
    async with AsyncExitStack() as stack:
        engine = create_engine(f"sqlite+aiosqlite:///{database_path}")
        stack.push_async_callback(engine.dispose)
        session_factory = create_session_factory(engine)
        http = await stack.enter_async_context(
            httpx.AsyncClient(timeout=settings.catalog_timeout_seconds)
        )
        deps = AgentDeps(
            models=ModelRegistry(settings),
            catalog=build_music_catalog(settings, http, TrackLinkCacheRepository(session_factory)),
            prompts=PromptLibrary.load(),
            repository=RecommendationRepository(session_factory),
        )
        yield EvalTarget(build_graph(InMemorySaver()), deps, with_youtube=with_youtube)
