"""Runs the agent graph for one request: start, pause for a clarifying question, resume.

Responsibilities around the graph itself:
- the `recommendations` row: created as pending, set to needs_clarification while the graph
  waits for an answer, failed with the error code when a run fails (`finalize` completes it);
- the exclusion list (recent recommendations) passed into the graph;
- the LangSmith root run: id, inputs, metadata and tags (implementation plan, 2.4).
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from langsmith.run_trees import RunTree

from app import __version__
from app.agents.graph import RecommendationGraph
from app.agents.schemas import Locale, Recommendation
from app.agents.state import CANDIDATE_COUNT, AgentDeps, GraphState
from app.db.models import InputMode, RecommendationStatus
from app.errors import AppError, ConflictError, NotFoundError
from app.llm.models import TIERS
from app.observability.tracing import Tracing, root_run_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Completed:
    recommendation: Recommendation


@dataclass(frozen=True)
class NeedsClarification:
    request_id: str
    question: str


RunOutcome = Completed | NeedsClarification


class RecommendationRunner:
    def __init__(
        self,
        graph: RecommendationGraph,
        deps: AgentDeps,
        tracing: Tracing,
        *,
        history_exclude_last_n: int,
    ) -> None:
        self._graph = graph
        self._deps = deps
        self._tracing = tracing
        self._history_exclude_last_n = history_exclude_last_n

    async def start(
        self, text: str, *, input_mode: InputMode, locale: Locale, transcript: str | None = None
    ) -> RunOutcome:
        """Start a recommendation. `transcript` is the raw speech transcript, if the (possibly
        edited) text came from voice input; it is recorded in the trace only."""
        request_id = str(uuid.uuid4())
        repository = self._deps.repository
        await repository.create(request_id, locale=locale, input_mode=input_mode, input_text=text)
        state: GraphState = {
            "request_id": request_id,
            "locale": locale,
            "user_input": text,
            "input_mode": input_mode.value,
            "excluded_tracks": await repository.recent_tracks(self._history_exclude_last_n),
        }
        inputs: dict[str, Any] = {
            "user_input": text,
            "input_mode": input_mode.value,
            "locale": locale,
        }
        if transcript is not None:
            inputs["transcript"] = transcript
        return await self._run(
            request_id, state, resumed=False, inputs=inputs, input_mode=input_mode, locale=locale
        )

    async def answer(self, request_id: str, answer: str) -> RunOutcome:
        """Resume a run paused at the clarifying question."""
        row = await self._deps.repository.get(request_id)
        if row is None:
            raise NotFoundError("Recommendation not found.")
        if row.status is not RecommendationStatus.NEEDS_CLARIFICATION:
            raise ConflictError("This recommendation is not waiting for an answer.")
        await self._deps.repository.save_clarification_answer(request_id, answer)
        locale: Locale = "pl" if row.locale == "pl" else "en"
        inputs = {
            "user_input": row.input_text,
            "input_mode": row.input_mode.value,
            "locale": locale,
            "clarification_question": row.clarification_question,
            "clarification_answer": answer,
        }
        return await self._run(
            request_id,
            Command(resume=answer),
            resumed=True,
            inputs=inputs,
            input_mode=row.input_mode,
            locale=locale,
        )

    async def _run(
        self,
        request_id: str,
        payload: GraphState | Command[Any],
        *,
        resumed: bool,
        inputs: dict[str, Any],
        input_mode: InputMode,
        locale: Locale,
    ) -> RunOutcome:
        run_id = root_run_id(request_id, resumed=resumed)
        tags = [input_mode.value, f"locale:{locale}", *(["clarified"] if resumed else [])]
        config: RunnableConfig = {"configurable": {"thread_id": request_id}}
        async with self._tracing.root_run(
            run_id=run_id, inputs=inputs, metadata=self._metadata(request_id, resumed), tags=tags
        ) as run:
            try:
                result: dict[str, Any] = await self._graph.ainvoke(
                    payload, config, context=self._deps
                )
            except Exception as exc:
                code = exc.code if isinstance(exc, AppError) else AppError.code
                logger.warning(
                    "Recommendation failed", extra={"request_id": request_id, "error_code": code}
                )
                await self._deps.repository.fail(request_id, code)
                raise
            outcome = await self._outcome(request_id, result)
            self._annotate(run, result, outcome)

        if isinstance(outcome, Completed):
            trace_url = await self._tracing.trace_url(run_id)
            outcome = Completed(outcome.recommendation.model_copy(update={"trace_url": trace_url}))
        return outcome

    async def _outcome(self, request_id: str, result: dict[str, Any]) -> RunOutcome:
        interrupts = result.get("__interrupt__")
        if interrupts:
            question = str(interrupts[0].value["question"])
            await self._deps.repository.mark_needs_clarification(
                request_id, question=question, need_profile=result.get("need_profile")
            )
            return NeedsClarification(request_id, question)
        return Completed(Recommendation.model_validate(result["recommendation"]))

    def _metadata(self, request_id: str, resumed: bool) -> dict[str, Any]:
        models = self._deps.models
        return {
            "request_id": request_id,
            # Groups the first run and the resumed run as one LangSmith thread (FR-44).
            "thread_id": request_id,
            "resumed": resumed,
            "app_version": __version__,
            "models": {tier: str(models.tier_config(tier).primary) for tier in TIERS},
            "fallback_models": {
                tier: str(fallback)
                for tier in TIERS
                if (fallback := models.tier_config(tier).fallback) is not None
            },
            "prompt_versions": self._deps.prompts.versions,
            # A prompt input, not part of the template: recorded so runs stay comparable.
            "candidate_count": CANDIDATE_COUNT,
        }

    @staticmethod
    def _annotate(run: RunTree, result: dict[str, Any], outcome: RunOutcome) -> None:
        """Metadata known only at the end of the run."""
        routing = result.get("routing") or {}
        escalations = result.get("escalations") or []
        metadata: dict[str, Any] = {
            "routing_complexity": routing.get("complexity"),
            "routing_source": routing.get("source"),
            "routing_reasons": routing.get("reasons"),
            "models_used": result.get("models_used", {}),
            "escalations": escalations,
            "curation_attempts": result.get("curation_attempts", 0),
        }
        tags: list[str] = []
        if escalations:
            tags.append("escalated")
        if isinstance(outcome, NeedsClarification):
            tags.append("clarified")
            metadata["status"] = "needs_clarification"
            run.end(outputs={"status": "needs_clarification", "question": outcome.question})
        else:
            rec = outcome.recommendation
            metadata |= {
                "status": "completed",
                "spotify_verified": rec.spotify_verified,
                "youtube_verified": rec.youtube_verified,
            }
            run.end(outputs={"status": "completed", "recommendation": rec.model_dump()})
        run.add_metadata(metadata)
        run.add_tags(tags)
