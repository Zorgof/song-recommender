"""Builders of Spotify / YouTube API responses and clients wired to respx-mocked HTTP."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import respx

from app.music import spotify, youtube
from app.music.spotify import SpotifyClient
from app.music.youtube import YouTubeClient
from tests.fakes import FAKE_BEARER_TOKEN, FAKE_GOOGLE_KEY

SPOTIFY_CLIENT_ID = "test-spotify-client"
SPOTIFY_CLIENT_SECRET = "test-spotify-secret"
SPOTIFY_TOKEN = FAKE_BEARER_TOKEN
SPOTIFY_SEARCH_URL = f"{spotify.API_URL}/search"
YOUTUBE_SEARCH_URL = youtube.SEARCH_URL
YOUTUBE_KEY = FAKE_GOOGLE_KEY


def spotify_track(
    track_id: str, name: str, *artists: str, image: str | None = "https://i.scdn.co/image/640"
) -> dict[str, Any]:
    return {
        "id": track_id,
        "name": name,
        "artists": [{"id": f"artist-{a}", "name": a} for a in artists],
        "album": {"images": [{"url": image, "width": 640, "height": 640}] if image else []},
        "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
        "popularity": 50,
    }


def spotify_search(*tracks: dict[str, Any] | None) -> httpx.Response:
    return httpx.Response(200, json={"tracks": {"items": list(tracks), "total": len(tracks)}})


def spotify_token(token: str = SPOTIFY_TOKEN, expires_in: int = 3600) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": token, "token_type": "Bearer", "expires_in": expires_in}
    )


def mock_spotify_token(mock: respx.MockRouter, *responses: httpx.Response) -> respx.Route:
    """Token endpoint answering `responses` in order, or always a valid token."""
    route = mock.post(spotify.TOKEN_URL)
    if responses:
        route.side_effect = list(responses)
    else:
        route.return_value = spotify_token()
    return route


def make_spotify(
    http: httpx.AsyncClient, clock: Callable[[], float] | None = None
) -> SpotifyClient:
    return SpotifyClient(
        http,
        SPOTIFY_CLIENT_ID,
        SPOTIFY_CLIENT_SECRET,
        "PL",
        **({"clock": clock} if clock else {}),
    )


def youtube_video(video_id: str, title: str, channel: str) -> dict[str, Any]:
    return {
        "kind": "youtube#searchResult",
        "id": {"kind": "youtube#video", "videoId": video_id},
        "snippet": {"title": title, "channelTitle": channel},
    }


def youtube_search(*items: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"kind": "youtube#searchListResponse", "items": list(items)})


def youtube_error(status: int, reason: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "error": {
                "code": status,
                "message": reason,
                "errors": [{"message": reason, "domain": "youtube.quota", "reason": reason}],
            }
        },
    )


def make_youtube(
    http: httpx.AsyncClient, now: Callable[[], datetime] | None = None
) -> YouTubeClient:
    return YouTubeClient(http, YOUTUBE_KEY, **({"now": now} if now else {}))


class FakeClock:
    """Settable time source for token expiry, quota resets and cache TTLs."""

    def __init__(self, start: datetime = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.now.timestamp()


def query_params(route: respx.Route, call: int = -1) -> dict[str, str]:
    return dict(route.calls[call].request.url.params)
