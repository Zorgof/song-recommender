from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import CatalogUnavailableError
from app.main import create_app
from app.music.cache import TrackLinkCacheRepository
from app.music.matching import normalized_key
from app.music.service import FOUND_TTL, NOT_FOUND_TTL, MusicCatalog, build_music_catalog
from app.music.spotify import SpotifyClient, SpotifyTrack
from app.music.youtube import YouTubeClient, YouTubeStatus
from tests.conftest import make_app_settings
from tests.fakes import FAKE_GOOGLE_KEY
from tests.music_fakes import (
    SPOTIFY_SEARCH_URL,
    YOUTUBE_SEARCH_URL,
    FakeClock,
    make_spotify,
    make_youtube,
    mock_spotify_token,
    spotify_search,
    spotify_track,
    youtube_error,
    youtube_search,
    youtube_video,
)

SessionFactory = async_sessionmaker[AsyncSession]

HURT = spotify_track("hurt-id", "Hurt - Remastered 2002", "Johnny Cash")
HURT_VIDEO = youtube_video("vid-1", "Johnny Cash - Hurt", "JohnnyCashVEVO")
KEY = normalized_key("Johnny Cash", "Hurt")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cache(session_factory: SessionFactory) -> TrackLinkCacheRepository:
    return TrackLinkCacheRepository(session_factory)


@pytest.fixture
def catalog(
    http: httpx.AsyncClient, cache: TrackLinkCacheRepository, clock: FakeClock
) -> MusicCatalog:
    return MusicCatalog(make_spotify(http), make_youtube(http, now=clock), cache, now=clock)


# --- Repository ---


async def test_repository_upserts_spotify_and_youtube_independently(
    cache: TrackLinkCacheRepository, clock: FakeClock
) -> None:
    track = SpotifyTrack("id-1", "Hurt", ("Johnny Cash",), "https://open.spotify.com/x", None)

    await cache.save_youtube(KEY, "vid-1", clock.now)
    await cache.save_spotify(KEY, track, clock.now)
    row = await cache.get(KEY)

    assert row is not None
    assert (row.spotify_track_id, row.spotify_title, row.spotify_artist) == (
        "id-1",
        "Hurt",
        "Johnny Cash",
    )
    assert (row.youtube_video_id, row.youtube_fetched_at) == ("vid-1", clock.now)
    assert row.spotify_fetched_at == clock.now

    # Re-saving as "not found" clears the Spotify columns but keeps the YouTube result.
    later = clock.now + timedelta(days=1)
    await cache.save_spotify(KEY, None, later)
    row = await cache.get(KEY)

    assert row is not None
    assert (row.spotify_track_id, row.spotify_url, row.spotify_fetched_at) == (None, None, later)
    assert row.youtube_video_id == "vid-1"


async def test_repository_get_unknown_key(cache: TrackLinkCacheRepository) -> None:
    assert await cache.get("nobody|nothing") is None


# --- Spotify through the cache ---


async def test_spotify_lookup_is_cached(
    catalog: MusicCatalog, respx_mock: respx.MockRouter
) -> None:
    mock_spotify_token(respx_mock)
    search = respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=spotify_search(HURT))

    first = await catalog.lookup_spotify("Hurt", "Johnny Cash")
    # Same song named slightly differently: same normalized key.
    second = await catalog.lookup_spotify("HURT (Remastered)", "johnny cash")

    assert search.call_count == 1
    assert first.from_cache is False and second.from_cache is True
    assert first.key == second.key == KEY
    assert first.track is not None and second.track is not None
    assert second.track.id == first.track.id == "hurt-id"
    assert second.track.url == first.track.url
    assert second.track.title == "Hurt - Remastered 2002"
    assert second.track.artist == "Johnny Cash"
    assert second.track.album_art_url == first.track.album_art_url


async def test_spotify_not_found_is_cached_for_a_shorter_time(
    catalog: MusicCatalog, respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    mock_spotify_token(respx_mock)
    cover = spotify_track("cover-id", "Hurt", "Christina Aguilera")
    search = respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=spotify_search(cover))

    first = await catalog.lookup_spotify("Hurt", "Johnny Cash")
    clock.now += NOT_FOUND_TTL - timedelta(seconds=1)
    cached = await catalog.lookup_spotify("Hurt", "Johnny Cash")

    assert first.track is None
    assert first.closest is not None and first.closest.id == "cover-id"
    assert first.closest_score is not None
    assert (cached.track, cached.from_cache, cached.closest) == (None, True, None)
    assert search.call_count == 2  # field-filtered + free-text search, once

    clock.now += timedelta(seconds=1)
    expired = await catalog.lookup_spotify("Hurt", "Johnny Cash")

    assert expired.from_cache is False
    assert search.call_count == 4


async def test_spotify_found_expires_after_its_ttl(
    catalog: MusicCatalog, respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    mock_spotify_token(respx_mock)
    search = respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=spotify_search(HURT))

    await catalog.lookup_spotify("Hurt", "Johnny Cash")
    clock.now += FOUND_TTL - timedelta(seconds=1)
    assert (await catalog.lookup_spotify("Hurt", "Johnny Cash")).from_cache is True
    clock.now += timedelta(seconds=1)
    assert (await catalog.lookup_spotify("Hurt", "Johnny Cash")).from_cache is False
    assert search.call_count == 2


async def test_spotify_errors_are_raised_and_not_cached(
    catalog: MusicCatalog, respx_mock: respx.MockRouter, cache: TrackLinkCacheRepository
) -> None:
    mock_spotify_token(respx_mock)
    respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=httpx.Response(503))

    with pytest.raises(CatalogUnavailableError):
        await catalog.lookup_spotify("Hurt", "Johnny Cash")
    assert await cache.get(KEY) is None


async def test_spotify_not_configured(
    http: httpx.AsyncClient, cache: TrackLinkCacheRepository
) -> None:
    catalog = MusicCatalog(None, make_youtube(http), cache)

    with pytest.raises(CatalogUnavailableError, match="not configured"):
        await catalog.lookup_spotify("Hurt", "Johnny Cash")


# --- YouTube through the cache ---


async def test_youtube_link_is_cached(catalog: MusicCatalog, respx_mock: respx.MockRouter) -> None:
    search = respx_mock.get(YOUTUBE_SEARCH_URL).mock(return_value=youtube_search(HURT_VIDEO))

    first = await catalog.youtube_link("Hurt", "Johnny Cash")
    second = await catalog.youtube_link("Hurt", "Johnny Cash")

    assert search.call_count == 1
    assert first.url == second.url == "https://www.youtube.com/watch?v=vid-1"
    assert first.verified and second.verified
    assert (first.from_cache, second.from_cache) == (False, True)


async def test_youtube_not_found_gives_a_search_link_and_is_cached(
    catalog: MusicCatalog, respx_mock: respx.MockRouter, clock: FakeClock
) -> None:
    search = respx_mock.get(YOUTUBE_SEARCH_URL).mock(return_value=youtube_search())

    first = await catalog.youtube_link("Hurt", "Johnny Cash")
    cached = await catalog.youtube_link("Hurt", "Johnny Cash")
    clock.now += NOT_FOUND_TTL
    await catalog.youtube_link("Hurt", "Johnny Cash")

    expected_url = "https://www.youtube.com/results?search_query=Johnny+Cash+Hurt"
    assert (first.url, first.verified, first.status) == (
        expected_url,
        False,
        YouTubeStatus.NOT_FOUND,
    )
    assert (cached.url, cached.verified, cached.from_cache) == (expected_url, False, True)
    assert search.call_count == 2


async def test_youtube_quota_exceeded_falls_back_to_a_search_link_without_caching(
    catalog: MusicCatalog,
    respx_mock: respx.MockRouter,
    cache: TrackLinkCacheRepository,
    clock: FakeClock,
) -> None:
    search = respx_mock.get(YOUTUBE_SEARCH_URL).mock(
        side_effect=[youtube_error(403, "quotaExceeded"), youtube_search(HURT_VIDEO)]
    )

    link = await catalog.youtube_link("Hurt", "Johnny Cash")
    again = await catalog.youtube_link("Hurt", "Johnny Cash")

    assert link.status is YouTubeStatus.QUOTA_EXCEEDED
    assert not link.verified
    assert link.url.startswith("https://www.youtube.com/results?search_query=")
    assert again.status is YouTubeStatus.QUOTA_EXCEEDED
    assert search.call_count == 1  # the second call did not reach the API
    assert await cache.get(KEY) is None

    clock.now += timedelta(days=1)
    recovered = await catalog.youtube_link("Hurt", "Johnny Cash")

    assert recovered.verified
    assert recovered.from_cache is False


async def test_youtube_not_configured_gives_a_search_link(
    http: httpx.AsyncClient, cache: TrackLinkCacheRepository
) -> None:
    catalog = MusicCatalog(make_spotify(http), None, cache)

    link = await catalog.youtube_link("Hurt", "Johnny Cash")

    assert (link.status, link.verified) == (YouTubeStatus.UNAVAILABLE, False)
    assert await cache.get(KEY) is None


async def test_spotify_and_youtube_share_one_cache_row(
    catalog: MusicCatalog, respx_mock: respx.MockRouter, cache: TrackLinkCacheRepository
) -> None:
    mock_spotify_token(respx_mock)
    respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=spotify_search(HURT))
    respx_mock.get(YOUTUBE_SEARCH_URL).mock(return_value=youtube_search(HURT_VIDEO))

    await catalog.lookup_spotify("Hurt", "Johnny Cash")
    await catalog.youtube_link("Hurt", "Johnny Cash")
    row = await cache.get(KEY)

    assert row is not None
    assert (row.spotify_track_id, row.youtube_video_id) == ("hurt-id", "vid-1")


# --- Construction from settings ---


def test_build_music_catalog_uses_configured_services(
    tmp_path: Path, http: httpx.AsyncClient, cache: TrackLinkCacheRepository
) -> None:
    settings = make_app_settings(
        tmp_path,
        spotify_client_id="id",
        spotify_client_secret="secret",
        youtube_api_key=FAKE_GOOGLE_KEY,
    )

    catalog = build_music_catalog(settings, http, cache)

    assert isinstance(catalog._spotify, SpotifyClient)
    assert isinstance(catalog._youtube, YouTubeClient)


def test_build_music_catalog_without_configuration(
    tmp_path: Path, http: httpx.AsyncClient, cache: TrackLinkCacheRepository
) -> None:
    catalog = build_music_catalog(make_app_settings(tmp_path), http, cache)

    assert catalog._spotify is None
    assert catalog._youtube is None


def test_app_exposes_the_catalog(app: FastAPI) -> None:
    with TestClient(app):
        assert isinstance(app.state.catalog, MusicCatalog)


def test_app_starts_with_catalogs_configured(tmp_path: Path) -> None:
    settings = make_app_settings(tmp_path, spotify_client_id="id", spotify_client_secret="secret")
    app = create_app(settings)

    with TestClient(app) as client:
        assert client.get("/api/meta").json()["catalogs"] == {"spotify": True, "youtube": False}
