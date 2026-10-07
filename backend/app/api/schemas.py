"""Response schemas of the system endpoints."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "error"]


class AppInfo(BaseModel):
    name: str
    version: str
    environment: str


class LLMInfo(BaseModel):
    """Configured `provider:model` per tier; never contains keys."""

    light: str | None
    heavy: str | None
    light_fallback: str | None
    heavy_fallback: str | None
    heavy_reasoning: bool


class STTInfo(BaseModel):
    enabled: bool
    provider: str


class CatalogsInfo(BaseModel):
    spotify: bool
    youtube: bool


class LangSmithInfo(BaseModel):
    enabled: bool
    project: str | None


class MetaResponse(BaseModel):
    app: AppInfo
    llm: LLMInfo
    stt: STTInfo
    catalogs: CatalogsInfo
    langsmith: LangSmithInfo
    locales: list[str]
