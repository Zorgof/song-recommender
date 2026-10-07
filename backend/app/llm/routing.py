"""Request complexity routing.

Hybrid routing (docs/implementation-plan.md, section 2.1): cheap heuristics decide the obvious
cases; only an "uncertain" verdict is sent to a light-model classifier (wired up in step 4).
The complexity then selects the tier of each agent through TIER_POLICY.
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.db.models import InputMode
from app.llm.models import Tier

Complexity = Literal["simple", "complex"]
HeuristicVerdict = Literal["simple", "complex", "uncertain"]

# Tiers used by (need analyst, music curator) for each complexity.
TIER_POLICY: dict[Complexity, tuple[Tier, Tier]] = {
    "simple": ("light", "light"),
    "complex": ("heavy", "heavy"),
}

# Below this many words there is too little to judge; the classifier (and possibly a
# clarifying question) decides.
MIN_WORDS = 5
# Up to this many words without contrast markers, a description is treated as simple.
SIMPLE_MAX_WORDS = {InputMode.TEXT: 60, InputMode.VOICE: 90}  # speech is wordier than typing
# From this many words on, a description is treated as complex.
COMPLEX_MIN_WORDS = 150
# This many contrast markers mean mixed or conflicting feelings.
COMPLEX_MIN_CONTRAST_MARKERS = 2

# Phrases signalling contrast, mixed feelings or uncertainty, in English and Polish.
CONTRAST_MARKERS: tuple[str, ...] = (
    # English
    "but",
    "however",
    "although",
    "though",
    "even though",
    "yet",
    "on the other hand",
    "at the same time",
    "mixed feelings",
    "torn",
    "conflicted",
    "not sure",
    "don't know",
    # Polish
    "ale",
    "jednak",
    "chociaż",
    "choć",
    "mimo że",
    "mimo to",
    "z jednej strony",
    "z drugiej strony",
    "jednocześnie",
    "a zarazem",
    "natomiast",
    "rozdarty",
    "rozdarta",
    "mieszane uczucia",
    "nie wiem",
)

_MARKER_PATTERNS = tuple(
    (marker, re.compile(rf"(?<!\w){re.escape(marker)}(?!\w)", re.IGNORECASE))
    for marker in CONTRAST_MARKERS
)
_WORD = re.compile(r"\w+(?:'\w+)?")


@dataclass(frozen=True)
class HeuristicAssessment:
    verdict: HeuristicVerdict
    reasons: tuple[str, ...]
    word_count: int
    contrast_markers: tuple[str, ...]


class RoutingDecision(BaseModel):
    """Recorded in the graph state and in the LangSmith trace metadata."""

    complexity: Complexity
    need_analyst_tier: Tier
    curator_tier: Tier
    source: Literal["heuristics", "classifier"]
    reasons: list[str]


def assess_complexity(text: str, input_mode: InputMode) -> HeuristicAssessment:
    # Typographic apostrophes (phones, transcripts) would break "don't" and word counting.
    text = text.replace("\u2019", "'")
    words = len(_WORD.findall(text))
    markers = tuple(marker for marker, pattern in _MARKER_PATTERNS if pattern.search(text))
    simple_max = SIMPLE_MAX_WORDS[input_mode]

    if words < MIN_WORDS:
        return HeuristicAssessment(
            "uncertain", (f"very short description ({words} words)",), words, markers
        )
    if words >= COMPLEX_MIN_WORDS:
        return HeuristicAssessment(
            "complex", (f"long description ({words} words)",), words, markers
        )
    if len(markers) >= COMPLEX_MIN_CONTRAST_MARKERS:
        return HeuristicAssessment(
            "complex", (f"mixed or conflicting feelings ({', '.join(markers)})",), words, markers
        )
    if words <= simple_max and not markers:
        return HeuristicAssessment(
            "simple", (f"short, single-toned description ({words} words)",), words, markers
        )

    reasons = []
    if markers:
        reasons.append(f"one contrast marker ({markers[0]})")
    if words > simple_max:
        reasons.append(f"medium-length description ({words} words)")
    return HeuristicAssessment("uncertain", tuple(reasons), words, markers)


def decide(
    complexity: Complexity, source: Literal["heuristics", "classifier"], reasons: list[str]
) -> RoutingDecision:
    need_analyst_tier, curator_tier = TIER_POLICY[complexity]
    return RoutingDecision(
        complexity=complexity,
        need_analyst_tier=need_analyst_tier,
        curator_tier=curator_tier,
        source=source,
        reasons=reasons,
    )
