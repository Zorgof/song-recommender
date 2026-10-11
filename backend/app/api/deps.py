"""FastAPI dependencies shared by the routers."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runner import RecommendationRunner
from app.config import Settings
from app.db.repositories import FeedbackRepository, RecommendationRepository
from app.errors import STTUnavailableError
from app.observability.tracing import Tracing
from app.stt.base import STTProvider


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_runner(request: Request) -> RecommendationRunner:
    runner: RecommendationRunner = request.app.state.recommender
    return runner


def get_tracing(request: Request) -> Tracing:
    tracing: Tracing = request.app.state.tracing
    return tracing


def get_recommendation_repository(request: Request) -> RecommendationRepository:
    return RecommendationRepository(request.app.state.session_factory)


def get_feedback_repository(request: Request) -> FeedbackRepository:
    return FeedbackRepository(request.app.state.session_factory)


def get_stt(request: Request) -> STTProvider:
    stt: STTProvider | None = request.app.state.stt
    if stt is None:
        raise STTUnavailableError("Speech-to-text is disabled.")
    return stt


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
RunnerDep = Annotated[RecommendationRunner, Depends(get_runner)]
TracingDep = Annotated[Tracing, Depends(get_tracing)]
RecommendationRepoDep = Annotated[RecommendationRepository, Depends(get_recommendation_repository)]
FeedbackRepoDep = Annotated[FeedbackRepository, Depends(get_feedback_repository)]
STTDep = Annotated[STTProvider, Depends(get_stt)]
