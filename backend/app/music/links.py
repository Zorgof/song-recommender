"""Public URLs of tracks and of catalog searches (the unverified fallback links)."""

from urllib.parse import quote, urlencode


def spotify_search_url(title: str, artist: str) -> str:
    return f"https://open.spotify.com/search/{quote(f'{artist} {title}', safe='')}"


def youtube_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?{urlencode({'v': video_id})}"


def youtube_search_url(title: str, artist: str) -> str:
    return f"https://www.youtube.com/results?{urlencode({'search_query': f'{artist} {title}'})}"
