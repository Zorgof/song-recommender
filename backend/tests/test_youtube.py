from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.music.youtube import MUSIC_CATEGORY_ID, YouTubeStatus, next_quota_reset
from tests.music_fakes import (
    YOUTUBE_KEY,
    YOUTUBE_SEARCH_URL,
    FakeClock,
    make_youtube,
    query_params,
    youtube_error,
    youtube_search,
    youtube_video,
)

HURT_VIDEO = youtube_video(
    "8AHCfZTRGiI", "Johnny Cash - Hurt (Official Music Video)", "JohnnyCashVEVO"
)


async def test_finds_matching_video(http: httpx.AsyncClient, respx_mock: respx.MockRouter) -> None:
    search = respx_mock.get(YOUTUBE_SEARCH_URL).mock(return_value=youtube_search(HURT_VIDEO))

    result = await make_youtube(http).find_video("Hurt - Remastered 2002", "Johnny Cash")

    assert result.status is YouTubeStatus.FOUND
    assert result.video_id == "8AHCfZTRGiI"
    request = search.calls[0].request
    assert query_params(search) == {
        "part": "snippet",
        "type": "video",
        "videoCategoryId": MUSIC_CATEGORY_ID,
        "maxResults": "5",
        "q": "Johnny Cash Hurt",
    }
    # The key is sent in a header and never appears in the URL.
    assert request.headers["X-Goog-Api-Key"] == YOUTUBE_KEY
    assert YOUTUBE_KEY not in str(request.url)


async def test_skips_videos_of_other_songs(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(YOUTUBE_SEARCH_URL).mock(
        return_value=youtube_search(
            youtube_video("nin", "Nine Inch Nails - Hurt", "NINVEVO"),
            youtube_video("rof", "Johnny Cash - Ring of Fire", "JohnnyCashVEVO"),
            youtube_video("topic", "Hurt", "Johnny Cash - Topic"),
        )
    )

    result = await make_youtube(http).find_video("Hurt", "Johnny Cash")

    assert (result.status, result.video_id) == (YouTubeStatus.FOUND, "topic")


async def test_html_entities_in_titles_are_decoded(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(YOUTUBE_SEARCH_URL).mock(
        return_value=youtube_search(
            youtube_video("q1", "Queen - Don&#39;t Stop Me Now (Official Video)", "Queen Official")
        )
    )

    result = await make_youtube(http).find_video("Don't Stop Me Now", "Queen")

    assert result.status is YouTubeStatus.FOUND
    assert result.video_title == "Queen - Don't Stop Me Now (Official Video)"


@pytest.mark.parametrize(
    "response",
    [
        youtube_search(),
        youtube_search(youtube_video("nin", "Nine Inch Nails - Hurt", "NINVEVO")),
        # Channels and playlists have no videoId.
        youtube_search(
            {"id": {"kind": "youtube#channel"}, "snippet": {"title": "Johnny Cash - Hurt"}}
        ),
    ],
    ids=["empty", "other-artist", "no-video-id"],
)
async def test_not_found(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter, response: httpx.Response
) -> None:
    respx_mock.get(YOUTUBE_SEARCH_URL).mock(return_value=response)

    result = await make_youtube(http).find_video("Hurt", "Johnny Cash")

    assert (result.status, result.video_id) == (YouTubeStatus.NOT_FOUND, None)


# --- Quota ---


@pytest.mark.parametrize("reason", ["quotaExceeded", "dailyLimitExceeded"])
async def test_quota_exceeded_blocks_calls_until_the_quota_resets(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter, reason: str
) -> None:
    # 2026-10-10 12:00 UTC = 04:00 in UTC-8; the next reset is 2026-10-11 08:00 UTC.
    clock = FakeClock(datetime(2026, 10, 10, 12, 0, tzinfo=UTC))
    search = respx_mock.get(YOUTUBE_SEARCH_URL).mock(
        side_effect=[youtube_error(403, reason), youtube_search(HURT_VIDEO)]
    )
    client = make_youtube(http, now=clock)

    first = await client.find_video("Hurt", "Johnny Cash")
    clock.now = datetime(2026, 10, 11, 7, 59, tzinfo=UTC)
    blocked = await client.find_video("Hurt", "Johnny Cash")

    assert first.status is YouTubeStatus.QUOTA_EXCEEDED
    assert blocked.status is YouTubeStatus.QUOTA_EXCEEDED
    assert client.quota_exhausted
    assert search.call_count == 1

    clock.now = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
    after_reset = await client.find_video("Hurt", "Johnny Cash")

    assert after_reset.status is YouTubeStatus.FOUND
    assert not client.quota_exhausted
    assert search.call_count == 2


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 10, 12, 0, tzinfo=UTC), datetime(2026, 10, 11, 8, 0, tzinfo=UTC)),
        # Still the previous day in UTC-8.
        (datetime(2026, 10, 11, 7, 59, tzinfo=UTC), datetime(2026, 10, 11, 8, 0, tzinfo=UTC)),
        (datetime(2026, 10, 11, 8, 0, tzinfo=UTC), datetime(2026, 10, 12, 8, 0, tzinfo=UTC)),
    ],
)
def test_next_quota_reset(now: datetime, expected: datetime) -> None:
    assert next_quota_reset(now) == expected


# --- Errors ---


@pytest.mark.parametrize(
    "response",
    [
        youtube_error(403, "forbidden"),
        youtube_error(400, "keyInvalid"),
        # A short-term rate limit is not the daily quota: no blocking.
        youtube_error(403, "rateLimitExceeded"),
        httpx.Response(500, text="Internal error"),
        httpx.Response(200, json={"items": "not-a-list"}),
        httpx.Response(200, text="<html>"),
    ],
    ids=["forbidden", "key-invalid", "rate-limit", "server-error", "bad-shape", "not-json"],
)
async def test_errors_are_unavailable_without_blocking(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter, response: httpx.Response
) -> None:
    search = respx_mock.get(YOUTUBE_SEARCH_URL).mock(return_value=response)
    client = make_youtube(http)

    results = [await client.find_video("Hurt", "Johnny Cash") for _ in range(2)]

    assert [r.status for r in results] == [YouTubeStatus.UNAVAILABLE] * 2
    assert not client.quota_exhausted
    assert search.call_count == 2


async def test_network_error_is_unavailable(
    http: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(YOUTUBE_SEARCH_URL).mock(side_effect=httpx.ConnectTimeout("slow"))

    result = await make_youtube(http).find_video("Hurt", "Johnny Cash")

    assert result.status is YouTubeStatus.UNAVAILABLE


def test_quota_reset_is_never_early_in_pacific_daylight_time() -> None:
    # Midnight PDT (UTC-7) is 07:00 UTC; the client waits until 08:00 UTC (one hour late).
    reset = next_quota_reset(datetime(2026, 7, 1, 12, 0, tzinfo=UTC))

    assert reset - datetime(2026, 7, 2, 7, 0, tzinfo=UTC) == timedelta(hours=1)
