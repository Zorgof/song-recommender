"""Normalization of song titles and artist names, and fuzzy matching against catalog results.

The curator (an LLM) names songs as people do ("Hurt", "Johnny Cash"); catalogs name them as
labels do ("Hurt - Remastered 2002", "Johnny Cash"). Both sides are normalized the same way and
then compared with rapidfuzz. A catalog track matches when both the title and the artist score
at least MATCH_THRESHOLD (0-100).
"""

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

MATCH_THRESHOLD = 85.0

# Words that mark a recording variant rather than a different song.
_VERSION_WORDS = (
    r"remaster(?:ed)?|live|version|edit|mono|stereo|mix|remix|demo|acoustic|unplugged|"
    r"deluxe|bonus|anniversary|explicit|clean|single|radio|instrumental|reprise|"
    r"soundtrack|from|feat\.?|ft\.?|featuring|with"
)
_VERSION_RE = re.compile(rf"\b(?:{_VERSION_WORDS})\b|\b\d{{4}}\b")
_BRACKETS_RE = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
# " - Remastered 2011", " - Live at Wembley", and the same after an en or em dash
_DASH_SUFFIX_RE = re.compile(r"\s+[-\u2013\u2014]\s+(.*)$")
_FEAT_TAIL_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s.*$", re.IGNORECASE)
# Separators between several artists named in one string.
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|;|/|&|\+|\s(?:x|and|feat\.?|ft\.?|featuring|with|vs\.?)\s)\s*", re.IGNORECASE
)
_NON_WORD_RE = re.compile(r"[\W_]+")
# Letters NFKD does not decompose into a base letter and a combining mark.
_LETTER_MAP = str.maketrans({"ł": "l", "đ": "d", "ø": "o", "æ": "ae", "œ": "oe", "\u0131": "i"})
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "`": "'", "\u00b4": "'"})


def _fold(text: str) -> str:
    """Case, accents and punctuation folded away: "Małomiasteczkowy!" -> "malomiasteczkowy"."""
    text = unicodedata.normalize("NFKD", text.translate(_APOSTROPHES).casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).translate(_LETTER_MAP)
    text = text.replace("'", "").replace("&", " and ")
    return " ".join(_NON_WORD_RE.sub(" ", text).split())


def strip_decorations(title: str) -> str:
    """Remove variant markers from a title, keeping the original case and accents.

    "Hurt - Remastered 2002" -> "Hurt", "Song (feat. X) [Live]" -> "Song",
    "(I Can't Get No) Satisfaction" -> unchanged (the brackets hold no variant marker).
    """
    text = title.translate(_APOSTROPHES)

    def drop_variant(match: re.Match[str]) -> str:
        return " " if _VERSION_RE.search(match.group(0).lower()) else match.group(0)

    text = _BRACKETS_RE.sub(drop_variant, text)
    suffix = _DASH_SUFFIX_RE.search(text)
    if suffix and _VERSION_RE.search(suffix.group(1).lower()):
        text = text[: suffix.start()]
    text = _FEAT_TAIL_RE.sub("", text)
    return " ".join(text.split()) or " ".join(title.split())


def title_variants(title: str) -> tuple[str, ...]:
    """Folded forms of a title that are compared: without variant markers, and additionally
    without any bracketed text ("(I Can't Get No) Satisfaction" vs "Satisfaction")."""
    stripped = strip_decorations(title)
    variants = [_fold(stripped), _fold(_BRACKETS_RE.sub(" ", stripped))]
    return tuple(dict.fromkeys(v for v in variants if v))


def normalize_artist(artist: str) -> str:
    folded = _fold(artist)
    folded = folded.removeprefix("the ")
    # "and" carries no identity: "Simon & Garfunkel" == "Simon and Garfunkel" == "Simon Garfunkel".
    return " ".join(word for word in folded.split() if word != "and")


def split_artists(artist: str) -> list[str]:
    """ "Calvin Harris feat. Dua Lipa" -> ["Calvin Harris", "Dua Lipa"]."""
    return [part for part in _ARTIST_SPLIT_RE.split(artist) if part.strip()]


def normalized_key(artist: str, title: str) -> str:
    """Stable "artist|title" key for the link cache and the exclusion list."""
    return f"{normalize_artist(artist)}|{_fold(strip_decorations(title))}"


def title_score(wanted: str, found: str) -> float:
    return max(
        (
            fuzz.token_sort_ratio(a, b)
            for a in title_variants(wanted)
            for b in title_variants(found)
        ),
        default=0.0,
    )


def artist_score(wanted: str, found: Sequence[str]) -> float:
    """Best score of the wanted artist string against the track's artists.

    Compared are the whole strings ("Simon & Garfunkel", "Calvin Harris & Dua Lipa" against all
    credited artists together) and every wanted artist against every credited artist, so naming
    either the main artist or one of the featured ones is enough.
    """
    if not found:
        return 0.0
    scores = [fuzz.token_sort_ratio(normalize_artist(wanted), normalize_artist(" ".join(found)))]
    for part in split_artists(wanted):
        for credited in found:
            scores.append(fuzz.ratio(normalize_artist(part), normalize_artist(credited)))
    return max(scores)


@dataclass(frozen=True)
class MatchScore:
    title: float
    artist: float
    # Tie-breakers between matches. The wanted artist against *all* credited artists: prefers
    # Brian Eno's own recording over one credited to "Brian Eno, Tyler Rix, Tolga Kashif".
    exact_artist: float
    # Title similarity before variant markers are removed; prefers "Hurt" over "Hurt - Live".
    exact_title: float

    @property
    def is_match(self) -> bool:
        return self.title >= MATCH_THRESHOLD and self.artist >= MATCH_THRESHOLD


def score(wanted_title: str, wanted_artist: str, title: str, artists: Sequence[str]) -> MatchScore:
    return MatchScore(
        title=title_score(wanted_title, title),
        artist=artist_score(wanted_artist, artists),
        exact_artist=fuzz.token_sort_ratio(
            normalize_artist(wanted_artist), normalize_artist(" ".join(artists))
        ),
        exact_title=fuzz.ratio(_fold(wanted_title), _fold(title)),
    )


@dataclass(frozen=True)
class Ranked[T]:
    item: T
    score: MatchScore


def rank[T](
    wanted_title: str,
    wanted_artist: str,
    items: Sequence[T],
    title_of: Callable[[T], str],
    artists_of: Callable[[T], Sequence[str]],
) -> list[Ranked[T]]:
    """Items ordered best first: matches before non-matches, then by score.

    Ties keep the catalog's own (relevance) order, as sorting is stable.
    """
    ranked = [
        Ranked(item, score(wanted_title, wanted_artist, title_of(item), artists_of(item)))
        for item in items
    ]
    ranked.sort(
        key=lambda r: (
            r.score.is_match,
            min(r.score.title, r.score.artist),
            r.score.exact_artist,
            r.score.exact_title,
        ),
        reverse=True,
    )
    return ranked


def video_matches(title: str, artist: str, video_title: str, channel_title: str) -> bool:
    """Whether a YouTube video is plausibly the wanted song.

    Video titles carry extra words ("Artist - Title (Official Video)"), so the wanted title must
    appear *in* the video title, and the artist in the video title or the channel name
    ("Johnny Cash - Topic", "DawidPodsiadloVEVO"; compared without spaces).
    """
    folded_video_title = _fold(video_title)
    title_ok = any(
        fuzz.partial_ratio(variant, folded_video_title) >= MATCH_THRESHOLD
        for variant in title_variants(title)
    )
    haystack = "".join(w for w in _fold(f"{video_title} {channel_title}").split() if w != "and")
    artist_ok = any(
        fuzz.partial_ratio(needle, haystack) >= MATCH_THRESHOLD
        for part in [artist, *split_artists(artist)]
        if (needle := normalize_artist(part).replace(" ", ""))
    )
    return title_ok and artist_ok
