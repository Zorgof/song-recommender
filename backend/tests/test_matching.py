import pytest

from app.music.matching import (
    MATCH_THRESHOLD,
    normalize_artist,
    normalized_key,
    rank,
    score,
    split_artists,
    strip_decorations,
    title_variants,
    video_matches,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Hurt - Remastered 2002", "Hurt"),
        ("Don't Stop Me Now - Remastered 2011", "Don't Stop Me Now"),
        ("Clocks (Live in Buenos Aires)", "Clocks"),
        ("Levitating (feat. DaBaby)", "Levitating"),
        ("Song [Radio Edit]", "Song"),
        ("One Dance feat. Wizkid", "One Dance"),
        ("Skyfall \u2013 From \u201cSkyfall\u201d", "Skyfall"),
        ("Paint It Black - Mono", "Paint It Black"),
        # Brackets and dashes without a variant marker belong to the title.
        ("(I Can't Get No) Satisfaction", "(I Can't Get No) Satisfaction"),
        ("Ob-La-Di, Ob-La-Da", "Ob-La-Di, Ob-La-Da"),
        ("Stop - Wait - Go", "Stop - Wait - Go"),
        # Nothing left after stripping: keep the original.
        ("(Live)", "(Live)"),
    ],
)
def test_strip_decorations(title: str, expected: str) -> None:
    assert strip_decorations(title) == expected


def test_title_variants_fold_case_accents_and_punctuation() -> None:
    assert title_variants("Małomiasteczkowy!") == ("malomiasteczkowy",)
    assert title_variants("(I Can\u2019t Get No) Satisfaction") == (
        "i cant get no satisfaction",
        "satisfaction",
    )


@pytest.mark.parametrize(
    ("artist", "expected"),
    [
        ("The Beatles", "beatles"),
        ("Simon & Garfunkel", "simon garfunkel"),
        ("Simon and Garfunkel", "simon garfunkel"),
        ("Dawid Podsiadło", "dawid podsiadlo"),
        ("Sigur Rós", "sigur ros"),
        ("Mø", "mo"),
    ],
)
def test_normalize_artist(artist: str, expected: str) -> None:
    assert normalize_artist(artist) == expected


@pytest.mark.parametrize(
    ("artist", "expected"),
    [
        ("Calvin Harris feat. Dua Lipa", ["Calvin Harris", "Dua Lipa"]),
        ("Drake ft. Wizkid, Kyla", ["Drake", "Wizkid", "Kyla"]),
        ("Lil Nas X", ["Lil Nas X"]),
        ("Silk Sonic x Bruno Mars", ["Silk Sonic", "Bruno Mars"]),
    ],
)
def test_split_artists(artist: str, expected: list[str]) -> None:
    assert split_artists(artist) == expected


def test_normalized_key_ignores_variants_case_and_accents() -> None:
    key = normalized_key("Dawid Podsiadło", "Małomiasteczkowy")

    assert key == "dawid podsiadlo|malomiasteczkowy"
    assert normalized_key("dawid podsiadlo", "MAŁOMIASTECZKOWY - Remastered") == key
    assert normalized_key("The Beatles", "Yesterday") == normalized_key("Beatles", "Yesterday")


@pytest.mark.parametrize(
    ("wanted_title", "wanted_artist", "title", "artists"),
    [
        ("Hurt", "Johnny Cash", "Hurt - Remastered 2002", ["Johnny Cash"]),
        (
            "I Can't Get No Satisfaction",
            "The Rolling Stones",
            "(I Can't Get No) Satisfaction - Mono Version",
            ["The Rolling Stones"],
        ),
        ("One Dance", "Drake feat. Wizkid", "One Dance", ["Drake", "Wizkid", "Kyla"]),
        ("One Dance", "Wizkid", "One Dance", ["Drake", "Wizkid", "Kyla"]),
        ("Małomiasteczkowy", "Dawid Podsiadlo", "Małomiasteczkowy", ["Dawid Podsiadło"]),
        ("The Boxer", "Simon and Garfunkel", "The Boxer", ["Simon & Garfunkel"]),
        ("Yesterday", "Beatles", "Yesterday - Remastered 2009", ["The Beatles"]),
        ("Don\u2019t Stop Me Now", "Queen", "Don't Stop Me Now - Remastered 2011", ["Queen"]),
        ("Levitating", "Dua Lipa", "Levitating (feat. DaBaby)", ["Dua Lipa", "DaBaby"]),
        ("Hey Jude", "The Beatles", "Hey Jude", ["The Beatles"]),
        # A small typo is tolerated.
        ("Bohemian Rapsody", "Queen", "Bohemian Rhapsody", ["Queen"]),
    ],
)
def test_matches(wanted_title: str, wanted_artist: str, title: str, artists: list[str]) -> None:
    result = score(wanted_title, wanted_artist, title, artists)

    assert result.is_match, result


@pytest.mark.parametrize(
    ("wanted_title", "wanted_artist", "title", "artists"),
    [
        # Same title, different artist (a cover or an unrelated song).
        ("Bohemian Rhapsody", "Queen", "Bohemian Rhapsody", ["Queen Latifah"]),
        ("Hurt", "Johnny Cash", "Hurt", ["Christina Aguilera"]),
        # Same artist, different song.
        ("Yesterday", "The Beatles", "Tomorrow Never Knows", ["The Beatles"]),
        ("Help!", "The Beatles", "Help Me Rhonda", ["The Beach Boys"]),
        ("Anything", "Someone", "Track", []),
    ],
)
def test_does_not_match(
    wanted_title: str, wanted_artist: str, title: str, artists: list[str]
) -> None:
    result = score(wanted_title, wanted_artist, title, artists)

    assert not result.is_match, result
    assert min(result.title, result.artist) < MATCH_THRESHOLD


def test_rank_prefers_matches_then_the_plain_version_then_catalog_order() -> None:
    tracks = [
        ("Hurt", ("Christina Aguilera",)),
        ("Hurt - Live", ("Johnny Cash",)),
        ("Hurt", ("Johnny Cash",)),
        ("Hurt", ("Johnny Cash",)),
    ]

    ranked = rank("Hurt", "Johnny Cash", tracks, lambda t: t[0], lambda t: t[1])

    assert [r.score.is_match for r in ranked] == [True, True, True, False]
    # The studio version wins over "Live"; between identical ones the catalog order is kept.
    assert ranked[0].item is tracks[2]
    assert ranked[1].item is tracks[3]
    assert ranked[2].item is tracks[1]


CASH = ("Hurt", "Johnny Cash")
PODSIADLO = ("Małomiasteczkowy", "Dawid Podsiadło")


@pytest.mark.parametrize(
    ("wanted", "video_title", "channel", "expected"),
    [
        (CASH, "Johnny Cash - Hurt (Official Music Video)", "JohnnyCashVEVO", True),
        (CASH, "Hurt", "Johnny Cash - Topic", True),
        (CASH, "Hurt", "JohnnyCashVEVO", True),
        (PODSIADLO, "Dawid Podsiadło - Małomiasteczkowy (Official Video)", "Kayax", True),
        (PODSIADLO, "Małomiasteczkowy", "DawidPodsiadloVEVO", True),
        # Wrong song by the right artist, or the right title by someone else.
        (CASH, "Johnny Cash - Ring of Fire", "JohnnyCashVEVO", False),
        (CASH, "Nine Inch Nails - Hurt", "NINVEVO", False),
    ],
)
def test_video_matches(
    wanted: tuple[str, str], video_title: str, channel: str, expected: bool
) -> None:
    assert video_matches(*wanted, video_title, channel) is expected
