"""System endpoints: health check and public configuration metadata."""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.deps import SessionDep, SettingsDep
from app.api.schemas import (
    AppInfo,
    CatalogsInfo,
    HealthResponse,
    LangSmithInfo,
    LLMInfo,
    MetaResponse,
    STTInfo,
)
from app.config import SUPPORTED_LOCALES

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(session: SessionDep, response: Response) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check: database is not reachable")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="unavailable", database="error")
    return HealthResponse(status="ok", database="ok")


@router.get("/meta")
async def meta(settings: SettingsDep) -> MetaResponse:
    """What is configured, for the frontend. Contains no secrets."""
    return MetaResponse(
        app=AppInfo(name="song-recommender", version=__version__, environment=settings.app_env),
        llm=LLMInfo(
            light=settings.llm_light,
            heavy=settings.llm_heavy,
            light_fallback=settings.llm_light_fallback,
            heavy_fallback=settings.llm_heavy_fallback,
            heavy_reasoning=settings.llm_heavy_reasoning,
        ),
        stt=STTInfo(enabled=settings.stt_enabled, provider=settings.stt_provider),
        catalogs=CatalogsInfo(
            spotify=settings.spotify_configured, youtube=settings.youtube_configured
        ),
        langsmith=LangSmithInfo(
            enabled=settings.langsmith_enabled,
            project=settings.langsmith_project if settings.langsmith_enabled else None,
        ),
        locales=list(SUPPORTED_LOCALES),
    )
