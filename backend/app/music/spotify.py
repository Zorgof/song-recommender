"""Spotify Web API client: Client Credentials token and track search.

Only the Search endpoint is used. Apps in Development Mode get at most 10 results per search.
Errors (network, 5xx, rate limiting, rejected credentials) raise CatalogUnavailableError; a
search that simply finds nothing returns an empty list.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.errors import CatalogUnavailableError
from app.music.matching import MatchScore, rank, strip_decorations

logger = logging.getLogger(__name__)

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
MAX_SEARCH_LIMIT = 10
# Refresh the token this long before it expires, so a request never carries an expired token.
TOKEN_EXPIRY_MARGIN_SECONDS = 60.0

# Characters with a meaning in Spotify's query syntax (field filters, quoted phrases).
_QUERY_SPECIAL = str.maketrans({'"': " ", ":": " "})


@dataclass(frozen=True)
class SpotifyTrack:
    id: str
    title: str
    artists: tuple[str, ...]
    url: str
    album_art_url: str | None

    @property
    def artist(self) -> str:
        return ", ".join(self.artists)


@dataclass(frozen=True)
class SpotifyMatch:
    """Result of looking up one wanted song: the best matching track, if any.

    `best` is the closest track even when it does not match (for the curator's feedback).
    """

    track: SpotifyTrack | None
    best: SpotifyTrack | None
    best_score: MatchScore | None


# --- Response models (only the fields that are used) ---


class _Token(BaseModel):
    access_token: str
    expires_in: int


class _Named(BaseModel):
    name: str


class _Image(BaseModel):
    url: str


class _Album(BaseModel):
    images: list[_Image] = []


class _ExternalUrls(BaseModel):
    spotify: str


class _Track(BaseModel):
    id: str
    name: str
    artists: list[_Named]
    album: _Album
    external_urls: _ExternalUrls

    def to_track(self) -> SpotifyTrack:
        return SpotifyTrack(
            id=self.id,
            title=self.name,
            artists=tuple(a.name for a in self.artists),
            url=self.external_urls.spotify,
            # Spotify lists album images widest first (640 px).
            album_art_url=self.album.images[0].url if self.album.images else None,
        )


class _Paging(BaseModel):
    # Items can be null for tracks that are unavailable in the market.
    items: list[_Track | None]


class _SearchResponse(BaseModel):
    tracks: _Paging


class SpotifyClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        client_id: str,
        client_secret: str,
        market: str,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._client_id = client_id
        self._client_secret = client_secret
        self._market = market
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def search_track(
        self, title: str, artist: str, *, limit: int = MAX_SEARCH_LIMIT
    ) -> list[SpotifyTrack]:
        """Search with field filters (`track:… artist:…`) in the configured market."""
        return await self._search(f"track:{_clean(title)} artist:{_clean(artist)}", limit)

    async def find_track(self, title: str, artist: str) -> SpotifyMatch:
        """Look up a song named by the curator and return the best fuzzy match.

        The field-filtered search is precise but misses when the wanted title differs from the
        catalog's ("I Can't Get No Satisfaction"); a free-text search is the second attempt.
        """
        wanted_title = strip_decorations(title)
        queries = (
            f"track:{_clean(wanted_title)} artist:{_clean(artist)}",
            _clean(f"{wanted_title} {artist}"),
        )
        found: list[SpotifyTrack] = []
        for query in queries:
            found.extend(await self._search(query, MAX_SEARCH_LIMIT))
            ranked = rank(title, artist, found, lambda t: t.title, lambda t: t.artists)
            if ranked and ranked[0].score.is_match:
                return SpotifyMatch(ranked[0].item, ranked[0].item, ranked[0].score)
        if not found:
            return SpotifyMatch(None, None, None)
        return SpotifyMatch(None, ranked[0].item, ranked[0].score)

    async def _search(self, query: str, limit: int) -> list[SpotifyTrack]:
        if not 1 <= limit <= MAX_SEARCH_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
        params = {"q": query, "type": "track", "market": self._market, "limit": limit}
        response = await self._get("/search", params)
        try:
            body = _SearchResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            logger.warning("Spotify returned an unexpected search response")
            raise CatalogUnavailableError("Spotify returned an unexpected response.") from exc
        return [item.to_track() for item in body.tracks.items if item is not None]

    async def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        for attempt in (1, 2):
            token = await self._access_token()
            response = await self._send(
                "GET",
                f"{API_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code == httpx.codes.UNAUTHORIZED and attempt == 1:
                # The token was revoked or expired early: get a new one and try once more.
                logger.info("Spotify token rejected; refreshing")
                self._invalidate_token(token)
                continue
            _raise_for_status(response, "search")
            return response
        raise AssertionError("unreachable")

    async def _access_token(self) -> str:
        async with self._token_lock:
            if self._token is None or self._clock() >= self._token_expires_at:
                await self._refresh_token()
            assert self._token is not None
            return self._token

    async def _refresh_token(self) -> None:
        response = await self._send(
            "POST",
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=httpx.BasicAuth(self._client_id, self._client_secret),
        )
        if response.status_code in (httpx.codes.BAD_REQUEST, httpx.codes.UNAUTHORIZED):
            logger.error("Spotify rejected the client credentials (check SPOTIFY_CLIENT_ID/SECRET)")
            raise CatalogUnavailableError("Spotify rejected the configured credentials.")
        _raise_for_status(response, "token")
        try:
            token = _Token.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise CatalogUnavailableError("Spotify returned an unexpected token response.") from exc
        self._token = token.access_token
        self._token_expires_at = self._clock() + token.expires_in - TOKEN_EXPIRY_MARGIN_SECONDS
        logger.debug("Spotify token refreshed", extra={"expires_in": token.expires_in})

    def _invalidate_token(self, token: str) -> None:
        # Only if no concurrent request has refreshed it already.
        if self._token == token:
            self._token = None

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("Spotify request failed", extra={"error_type": type(exc).__name__})
            raise CatalogUnavailableError("Spotify could not be reached.") from exc


def _raise_for_status(response: httpx.Response, operation: str) -> None:
    if response.is_success:
        return
    extra: dict[str, Any] = {"operation": operation, "status": response.status_code}
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        extra["retry_after"] = response.headers.get("Retry-After")
        logger.warning("Spotify rate limit reached", extra=extra)
        raise CatalogUnavailableError("Spotify rate limit reached.")
    logger.warning("Spotify request returned an error", extra=extra)
    raise CatalogUnavailableError("Spotify returned an error.")


def _clean(text: str) -> str:
    return " ".join(text.translate(_QUERY_SPECIAL).split())
