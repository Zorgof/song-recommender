"""Application factory.

Run in development with:
    uv run uvicorn app.main:create_app --factory --reload
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import system
from app.config import Settings, get_settings
from app.db.migrate import upgrade_to_head_async
from app.db.session import create_engine, create_session_factory
from app.errors import register_error_handlers
from app.llm.models import ModelRegistry
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)

API_PREFIX = "/api"
REQUEST_ID_HEADER = "X-Request-ID"
# Polled by Docker healthchecks; logged at DEBUG so it does not flood the log.
_QUIET_PATHS = frozenset({f"{API_PREFIX}/health"})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    await upgrade_to_head_async(settings.database_path)
    engine = create_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    logger.info(
        "Application started",
        extra={"environment": settings.app_env, "database": str(settings.database_path)},
    )
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("Application stopped")


async def _log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        level = logging.DEBUG if request.url.path in _QUIET_PATHS else logging.INFO
        logger.log(
            level,
            "%s %s %s",
            request.method,
            request.url.path,
            status_code,
            extra={
                "request_id": request_id,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Song Recommender API",
        version=__version__,
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.state.settings = settings
    # Validates the LLM configuration; a bad .env stops the app here with a clear message.
    app.state.models = ModelRegistry(settings)

    if settings.is_development:
        # In production the SPA is served by nginx on the same origin, so CORS is not needed.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[REQUEST_ID_HEADER],
        )
    app.middleware("http")(_log_requests)
    register_error_handlers(app)
    app.include_router(system.router, prefix=API_PREFIX)
    return app
