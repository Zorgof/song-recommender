import base64
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.errors import CatalogUnavailableError
from app.music.spotify import MAX_SEARCH_LIMIT, TOKEN_EXPIRY_MARGIN_SECONDS
from tests.music_fakes import (
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    SPOTIFY_SEARCH_URL,
    SPOTIFY_TOKEN,
    FakeClock,
    make_spotify,
    mock_spotify_token,
    query_params,
    spotify_search,
    spotify_token,
    spotify_track,
)

HURT = spotify_track("hurt-id", "Hurt - Remastered 2002", "Johnny Cash")
HURT_COVER = spotify_track("cover-id", "Hurt", "Christina Aguilera")


async def test_find_track_matches_with_field_filtered_search(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    token = mock_spotify_token(respx_mock)
    search = respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=spotify_search(HURT_COVER, HURT))

    match = await make_spotify(http).find_track("Hurt", "Johnny Cash")

    assert match.track is not None
    assert match.track.id == "hurt-id"
    assert match.track.title == "Hurt - Remastered 2002"
    assert match.track.artists == ("Johnny Cash",)
    assert match.track.url == "https://open.spotify.com/track/hurt-id"
    assert match.track.album_art_url == "https://i.scdn.co/image/640"
    assert match.best_score is not None and match.best_score.is_match
    assert search.call_count == 1
    assert query_params(search) == {
        "q": "track:Hurt artist:Johnny Cash",
        "type": "track",
        "market": "PL",
        "limit": str(MAX_SEARCH_LIMIT),
    }
    assert search.calls[0].request.headers["Authorization"] == f"Bearer {SPOTIFY_TOKEN}"
    token_request = token.calls[0].request
    assert parse_qs(token_request.content.decode()) == {"grant_type": ["client_credentials"]}
    expected_basic = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode())
    assert token_request.headers["Authorization"] == f"Basic {expected_basic.decode()}"


async def test_find_track_falls_back_to_free_text_search(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    mock_spotify_token(respx_mock)
    satisfaction = spotify_track(
        "sat-id", "(I Can't Get No) Satisfaction - Mono Version", "The Rolling Stones"
    )
    search = respx_mock.get(SPOTIFY_SEARCH_URL).mock(
        side_effect=[spotify_search(), spotify_search(satisfaction)]
    )

    match = await make_spotify(http).find_track(
        "I Can't Get No Satisfaction (Remastered)", "The Rolling Stones"
    )

    assert match.track is not None and match.track.id == "sat-id"
    # Variant markers are left out of both queries; the second one has no field filters.
    assert [query_params(search, i)["q"] for i in range(2)] == [
        "track:I Can't Get No Satisfaction artist:The Rolling Stones",
        "I Can't Get No Satisfaction The Rolling Stones",
    ]


async def test_find_track_without_match_reports_the_closest_track(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    mock_spotify_token(respx_mock)
    search = respx_mock.get(SPOTIFY_SEARCH_URL).mock(
        side_effect=[spotify_search(HURT_COVER), spotify_search(HURT_COVER)]
    )

    match = await make_spotify(http).find_track("Hurt", "Johnny Cash")

    assert match.track is None
    assert match.best is not None and match.best.id == "cover-id"
    assert match.best_score is not None and not match.best_score.is_match
    assert search.call_count == 2


async def test_find_track_with_no_results_at_all(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    mock_spotify_token(respx_mock)
    respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=spotify_search())

    match = await make_spotify(http).find_track("Invented Song", "Nobody")

    assert (match.track, match.best, match.best_score) == (None, None, None)


async def test_query_syntax_characters_are_removed(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    mock_spotify_token(respx_mock)
    search = respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=spotify_search())

    await make_spotify(http).search_track('Song: "Quoted"', "Artist")

    assert query_params(search)["q"] == "track:Song Quoted artist:Artist"


async def test_null_items_and_missing_album_art(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    mock_spotify_token(respx_mock)
    respx_mock.get(SPOTIFY_SEARCH_URL).mock(
        return_value=spotify_search(None, spotify_track("id", "Song", "Artist", image=None))
    )

    tracks = await make_spotify(http).search_track("Song", "Artist")

    assert [(t.id, t.album_art_url) for t in tracks] == [("id", None)]


@pytest.mark.parametrize("limit", [0, MAX_SEARCH_LIMIT + 1])
async def test_search_limit_is_bounded(http: httpx.AsyncClient, limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        await make_spotify(http).search_track("Song", "Artist", limit=limit)


# --- Token caching and refresh ---


async def test_token_is_cached_between_searches(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    token = mock_spotify_token(respx_mock)
    respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=spotify_search())
    client = make_spotify(http)

    for _ in range(3):
        await client.search_track("Song", "Artist")

    assert token.call_count == 1


async def test_token_is_refreshed_before_it_expires(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    clock = FakeClock()
    token = mock_spotify_token(
        respx_mock, spotify_token("first", expires_in=3600), spotify_token("second")
    )
    search = respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=spotify_search())
    client = make_spotify(http, clock=clock.monotonic)

    await client.search_track("Song", "Artist")
    clock.now += timedelta(seconds=3600 - TOKEN_EXPIRY_MARGIN_SECONDS - 1)
    await client.search_track("Song", "Artist")
    clock.now += timedelta(seconds=1)
    await client.search_track("Song", "Artist")

    assert token.call_count == 2
    used = [call.request.headers["Authorization"] for call in search.calls]
    assert used == ["Bearer first", "Bearer first", "Bearer second"]


async def test_rejected_token_is_refreshed_and_the_search_retried_once(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    token = mock_spotify_token(respx_mock, spotify_token("revoked"), spotify_token("fresh"))
    search = respx_mock.get(SPOTIFY_SEARCH_URL).mock(
        side_effect=[httpx.Response(401), spotify_search(HURT)]
    )

    match = await make_spotify(http).find_track("Hurt", "Johnny Cash")

    assert match.track is not None
    assert token.call_count == 2
    assert search.calls[1].request.headers["Authorization"] == "Bearer fresh"


async def test_search_rejected_twice_is_an_error(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    mock_spotify_token(respx_mock)
    search = respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=httpx.Response(401))

    with pytest.raises(CatalogUnavailableError):
        await make_spotify(http).search_track("Song", "Artist")
    assert search.call_count == 2


@pytest.mark.parametrize("status", [400, 401])
async def test_rejected_credentials(
    http: httpx.AsyncClient,
    respx_mock: respx.MockRouter,
    status: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_spotify_token(respx_mock, httpx.Response(status, json={"error": "invalid_client"}))

    with pytest.raises(CatalogUnavailableError, match="credentials"):
        await make_spotify(http).search_track("Song", "Artist")
    assert "SPOTIFY_CLIENT_ID" in caplog.text
    assert SPOTIFY_CLIENT_SECRET not in caplog.text


# --- Errors ---


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(429, headers={"Retry-After": "30"}), "rate limit"),
        (httpx.Response(500), "error"),
        (httpx.Response(503), "error"),
        (httpx.Response(200, json={"unexpected": True}), "unexpected"),
        (httpx.Response(200, text="<html>"), "unexpected"),
    ],
)
async def test_search_errors_raise_catalog_unavailable(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter, response: httpx.Response, message: str
) -> None:
    mock_spotify_token(respx_mock)
    respx_mock.get(SPOTIFY_SEARCH_URL).mock(return_value=response)

    with pytest.raises(CatalogUnavailableError, match=message):
        await make_spotify(http).search_track("Song", "Artist")


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
async def test_network_errors_raise_catalog_unavailable(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter, exc: Exception
) -> None:
    mock_spotify_token(respx_mock)
    respx_mock.get(SPOTIFY_SEARCH_URL).mock(side_effect=exc)

    with pytest.raises(CatalogUnavailableError, match="reached"):
        await make_spotify(http).search_track("Song", "Artist")


async def test_token_endpoint_unreachable(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post("https://accounts.spotify.com/api/token").mock(
        side_effect=httpx.ConnectError("refused")
    )

    with pytest.raises(CatalogUnavailableError, match="reached"):
        await make_spotify(http).search_track("Song", "Artist")
