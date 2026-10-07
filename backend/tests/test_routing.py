import pytest

from app.db.models import InputMode
from app.llm.routing import (
    COMPLEX_MIN_WORDS,
    SIMPLE_MAX_WORDS,
    TIER_POLICY,
    Complexity,
    assess_complexity,
    decide,
)


def words(n: int) -> str:
    return " ".join(["calm"] * n)


@pytest.mark.parametrize(
    "text",
    [
        "Tired after a long day at work, I want something calm to unwind.",
        "Jestem zmęczony po pracy i chcę się wyciszyć przed snem.",
        "Great workout today, I feel strong and full of energy!",
    ],
)
def test_short_single_toned_descriptions_are_simple(text: str) -> None:
    result = assess_complexity(text, InputMode.TEXT)

    assert result.verdict == "simple"
    assert result.contrast_markers == ()


@pytest.mark.parametrize("text", ["ok day", "meh", "zmęczony", "", "   "])
def test_very_short_descriptions_are_uncertain(text: str) -> None:
    result = assess_complexity(text, InputMode.TEXT)

    assert result.verdict == "uncertain"
    assert "very short" in result.reasons[0]


@pytest.mark.parametrize(
    ("text", "markers"),
    [
        (
            "I got the job, but I'm sad to leave my team, although I know it's for the best.",
            ("but", "although"),
        ),
        (
            "Z jednej strony cieszę się z urlopu, z drugiej strony boję się powrotu.",
            ("z jednej strony", "z drugiej strony"),
        ),
        ("Happy yet nervous, I don\u2019t know what I need tonight.", ("yet", "don't know")),
    ],
)
def test_mixed_feelings_are_complex(text: str, markers: tuple[str, ...]) -> None:
    result = assess_complexity(text, InputMode.TEXT)

    assert result.verdict == "complex"
    assert set(markers) <= set(result.contrast_markers)


def test_a_single_contrast_marker_is_uncertain() -> None:
    result = assess_complexity("Good day overall, but a bit tired in the evening.", InputMode.TEXT)

    assert result.verdict == "uncertain"
    assert result.reasons == ("one contrast marker (but)",)


def test_markers_match_whole_words_only() -> None:
    # "but" inside "button", "ale" inside "alergia", "though" inside "although" (counted once).
    text = "Pressed the button, my alergia is gone, although rain."
    result = assess_complexity(text, InputMode.TEXT)

    assert result.contrast_markers == ("although",)


def test_long_descriptions_are_complex() -> None:
    result = assess_complexity(words(COMPLEX_MIN_WORDS), InputMode.TEXT)

    assert result.verdict == "complex"
    assert result.word_count == COMPLEX_MIN_WORDS


def test_medium_length_is_uncertain() -> None:
    result = assess_complexity(words(SIMPLE_MAX_WORDS[InputMode.TEXT] + 1), InputMode.TEXT)

    assert result.verdict == "uncertain"
    assert "medium-length" in result.reasons[0]


def test_voice_input_allows_more_words_for_simple() -> None:
    text = words(SIMPLE_MAX_WORDS[InputMode.TEXT] + 10)

    assert assess_complexity(text, InputMode.TEXT).verdict == "uncertain"
    assert assess_complexity(text, InputMode.VOICE).verdict == "simple"


def test_typographic_apostrophes_do_not_split_words() -> None:
    assert assess_complexity("I don\u2019t feel great today", InputMode.TEXT).word_count == 5


@pytest.mark.parametrize("complexity", ["simple", "complex"])
def test_decide_applies_tier_policy(complexity: Complexity) -> None:
    decision = decide(complexity, "heuristics", ["reason"])

    assert (decision.need_analyst_tier, decision.curator_tier) == TIER_POLICY[complexity]
    assert decision.source == "heuristics"
    assert decision.reasons == ["reason"]


def test_tier_policy() -> None:
    assert TIER_POLICY == {"simple": ("light", "light"), "complex": ("heavy", "heavy")}
