"""YouTube Data API v3 client: one `search.list` call per song, in the Music category.

The free quota is 10,000 units a day and a search costs 100, so about 100 searches a day. This
client never raises for API or network errors: the caller then uses a search URL instead (FR-17).
After a quota error no further calls are made until the quota resets (midnight Pacific time).
"""

import html
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.music.matching import strip_decorations, video_matches

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
MUSIC_CATEGORY_ID = "10"
MAX_RESULTS = 5
# Error reasons that mean the daily quota is used up (not a short-term rate limit).
QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded"})
# The quota resets at midnight Pacific Time. Standard time (UTC-8) is used all year: during
# daylight saving time calls resume an hour late, never early (an early call would fail again).
QUOTA_RESET_TZ = timezone(timedelta(hours=-8))


class YouTubeStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    QUOTA_EXCEEDED = "quota_exceeded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class YouTubeSearchResult:
    status: YouTubeStatus
    video_id: str | None = None
    video_title: str | None = None


# --- Response models (only the fields that are used) ---


class _VideoId(BaseModel):
    videoId: str | None = None


class _Snippet(BaseModel):
    title: str
    channelTitle: str = ""


class _Item(BaseModel):
    id: _VideoId
    snippet: _Snippet


class _SearchResponse(BaseModel):
    items: list[_Item] = []


def next_quota_reset(now: datetime) -> datetime:
    local = now.astimezone(QUOTA_RESET_TZ)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class YouTubeClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._now = now
        self._quota_blocked_until: datetime | None = None

    @property
    def quota_exhausted(self) -> bool:
        return self._quota_blocked_until is not None and self._now() < self._quota_blocked_until

    async def find_video(self, title: str, artist: str) -> YouTubeSearchResult:
        if self.quota_exhausted:
            return YouTubeSearchResult(YouTubeStatus.QUOTA_EXCEEDED)

        params: dict[str, Any] = {
            "part": "snippet",
            "type": "video",
            "videoCategoryId": MUSIC_CATEGORY_ID,
            "maxResults": MAX_RESULTS,
            "q": f"{artist} {strip_decorations(title)}",
        }
        try:
            # The key goes in a header, so it never appears in URLs (logs, exceptions).
            response = await self._http.get(
                SEARCH_URL, params=params, headers={"X-Goog-Api-Key": self._api_key}
            )
        except httpx.HTTPError as exc:
            logger.warning("YouTube request failed", extra={"error_type": type(exc).__name__})
            return YouTubeSearchResult(YouTubeStatus.UNAVAILABLE)

        if not response.is_success:
            return self._handle_error(response)
        try:
            body = _SearchResponse.model_validate(response.json())
        except ValueError, ValidationError:
            logger.warning("YouTube returned an unexpected search response")
            return YouTubeSearchResult(YouTubeStatus.UNAVAILABLE)

        for item in body.items:
            video_title = html.unescape(item.snippet.title)
            channel = html.unescape(item.snippet.channelTitle)
            if item.id.videoId and video_matches(title, artist, video_title, channel):
                return YouTubeSearchResult(YouTubeStatus.FOUND, item.id.videoId, video_title)
        return YouTubeSearchResult(YouTubeStatus.NOT_FOUND)

    def _handle_error(self, response: httpx.Response) -> YouTubeSearchResult:
        reasons = _error_reasons(response)
        if reasons & QUOTA_REASONS:
            self._quota_blocked_until = next_quota_reset(self._now())
            logger.warning(
                "YouTube quota exceeded; using search links until the quota resets",
                extra={"until": self._quota_blocked_until.isoformat()},
            )
            return YouTubeSearchResult(YouTubeStatus.QUOTA_EXCEEDED)
        logger.warning(
            "YouTube request returned an error",
            extra={"status": response.status_code, "reasons": sorted(reasons)},
        )
        return YouTubeSearchResult(YouTubeStatus.UNAVAILABLE)


def _error_reasons(response: httpx.Response) -> set[str]:
    """Reasons from Google's error body: {"error": {"errors": [{"reason": ...}]}}."""
    try:
        errors = response.json()["error"]["errors"]
        return {str(e["reason"]) for e in errors if "reason" in e}
    except ValueError, KeyError, TypeError:
        return set()
