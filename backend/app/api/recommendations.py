"""Recommendation endpoints: start, answer the clarifying question, history, feedback."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.agents.runner import Completed, NeedsClarification, RunOutcome
from app.api.deps import FeedbackRepoDep, RecommendationRepoDep, RunnerDep, TracingDep
from app.api.recommendation_schemas import (
    SCORE_VALUES,
    ClarificationRequest,
    CompletedResponse,
    FeedbackOut,
    FeedbackRequest,
    HistoryItem,
    HistoryPage,
    NeedsClarificationResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from app.db.models import Recommendation, RecommendationStatus
from app.errors import ConflictError, NotFoundError
from app.observability.tracing import Tracing, root_run_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

MAX_PAGE_SIZE = 100


def _response(outcome: RunOutcome) -> CompletedResponse | NeedsClarificationResponse:
    if isinstance(outcome, NeedsClarification):
        return NeedsClarificationResponse(request_id=outcome.request_id, question=outcome.question)
    assert isinstance(outcome, Completed)
    return CompletedResponse(recommendation=outcome.recommendation)


def final_run_id(row: Recommendation) -> uuid.UUID:
    """The run that produced the recommendation: the resumed one if a question was answered."""
    return root_run_id(row.id, resumed=row.clarification_answer is not None)


@router.post("")
async def create_recommendation(
    body: RecommendationRequest, runner: RunnerDep
) -> RecommendationResponse:
    """Recommend one song, or return a clarifying question (answer it with /clarification)."""
    outcome = await runner.start(body.text, input_mode=body.input_mode, locale=body.locale)
    return _response(outcome)


@router.post("/{request_id}/clarification")
async def answer_clarification(
    request_id: str, body: ClarificationRequest, runner: RunnerDep
) -> RecommendationResponse:
    """Resume a recommendation that is waiting for the answer to its clarifying question."""
    return _response(await runner.answer(request_id, body.answer))


@router.get("")
async def list_recommendations(
    repository: RecommendationRepoDep,
    tracing: TracingDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HistoryPage:
    """Completed recommendations, newest first, with their feedback."""
    rows, total = await repository.list_completed(limit=limit, offset=offset)
    items = [await _history_item(row, tracing) for row in rows]
    return HistoryPage(items=items, total=total, limit=limit, offset=offset)


async def _history_item(row: Recommendation, tracing: Tracing) -> HistoryItem:
    feedback = row.feedback
    return HistoryItem(
        request_id=row.id,
        created_at=row.created_at,
        locale=row.locale,
        input_mode=row.input_mode,
        input_text=row.input_text,
        clarification_question=row.clarification_question,
        clarification_answer=row.clarification_answer,
        title=row.title,
        artist=row.artist,
        album_art_url=row.album_art_url,
        spotify_url=row.spotify_url,
        spotify_track_id=row.spotify_track_id,
        spotify_verified=row.spotify_verified,
        youtube_url=row.youtube_url,
        youtube_verified=row.youtube_verified,
        explanation=row.explanation,
        need_summary=row.need_summary,
        trace_url=await tracing.trace_url(final_run_id(row)),
        feedback=(
            FeedbackOut(
                score="up" if feedback.score == 1 else "down",
                comment=feedback.comment,
                synced_to_langsmith=feedback.synced_to_langsmith,
            )
            if feedback
            else None
        ),
    )


@router.post("/{request_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def give_feedback(
    request_id: str,
    body: FeedbackRequest,
    recommendations: RecommendationRepoDep,
    feedback: FeedbackRepoDep,
    tracing: TracingDep,
) -> Response:
    """Rate a completed recommendation (rating again replaces the earlier rating).

    The rating is always stored locally; it is also sent to LangSmith as feedback on the run
    that produced the recommendation. If that fails, it is kept as not synced.
    """
    row = await recommendations.get(request_id)
    if row is None:
        raise NotFoundError("Recommendation not found.")
    if row.status is not RecommendationStatus.COMPLETED:
        raise ConflictError("Only completed recommendations can be rated.")

    score = SCORE_VALUES[body.score]
    comment = body.comment or None
    await feedback.save(request_id, score=score, comment=comment)
    if await tracing.send_feedback(request_id, final_run_id(row), score=score, comment=comment):
        await feedback.mark_synced(request_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
