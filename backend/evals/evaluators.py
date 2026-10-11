"""Evaluators of an experiment (implementation plan, step 10).

Per example (LangSmith averages each key over the experiment, so 0/1 scores read as rates):

| Key | Meaning |
|-----|---------|
| `completed` | 1 if a recommendation was produced, 0 if the run failed |
| `spotify_verified` | 1 if the song was verified on Spotify (FR-13) |
| `youtube_verified` | 1 if a YouTube video was found; only with `--with-youtube` |
| `latency_s` | end-to-end seconds, including a clarification round trip |
| `within_15s` | 1 if latency_s <= 15 (NFR-3) |
| `escalated` | 1 if any escalation to the heavy tier happened |
| `curation_attempts` | number of curator attempts (1 = verified on the first try) |
| `clarified` | 1 if the agents asked a clarifying question |
| `explanation_language` | 1 if the explanation and the need summary are in the UI locale (FR-15) |
| `fit` | LLM-as-judge fit of the song to the need: the four aspects below, 0-8 mapped to 0-1 |
| `fit_<aspect>` | the judge's score of energy, goal, requests, specificity: 0-2 to 0-1 |
| `profile_faithful` | judge: 1 if the Need Profile is a faithful reading of the description |

Over the whole experiment (summary evaluator): `distinct_songs` and `distinct_artists`, the
number of different songs (artists) divided by the number of recommendations; 1.0 means
nothing was recommended twice. The comment lists what repeated.
"""

import json
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.agents.prompt_loader import PromptTemplate, load_prompt
from app.llm.models import ModelRegistry, Tier
from app.llm.structured import structured_call
from app.music.matching import normalize_artist, normalized_key

NFR_LATENCY_S = 15.0
JUDGE_PROMPTS_DIR = Path(__file__).with_name("prompts")

Result = dict[str, Any]


def _result(key: str, score: float | bool | None, comment: str | None = None) -> Result:
    result: Result = {"key": key, "score": score}
    if comment:
        result["comment"] = comment
    return result


def _completed(outputs: dict[str, Any]) -> bool:
    return outputs.get("status") == "completed" and bool(outputs.get("recommendation"))


# --- Deterministic evaluators ---


def outcome(outputs: dict[str, Any]) -> dict[str, list[Result]]:
    """Completion, verification, escalation, clarification and latency."""
    latency = outputs.get("latency_s")
    results = [
        _result("completed", int(_completed(outputs)), outputs.get("error_code")),
        _result(
            "clarified", int(bool(outputs.get("clarified"))), outputs.get("clarification_question")
        ),
        _result("latency_s", latency),
        _result("within_15s", None if latency is None else int(latency <= NFR_LATENCY_S)),
    ]
    if not _completed(outputs):
        return {"results": [*results, _result("spotify_verified", 0), _result("escalated", None)]}
    rec = outputs["recommendation"]
    escalations = outputs.get("escalations") or []
    results += [
        _result(
            "spotify_verified", int(rec["spotify_verified"]), f"{rec['artist']} - {rec['title']}"
        ),
        _result(
            "escalated",
            int(bool(escalations)),
            "; ".join(f"{e['node']}: {e['reason']}" for e in escalations) or None,
        ),
        _result("curation_attempts", outputs.get("curation_attempts")),
    ]
    if outputs.get("youtube_checked"):
        results.append(_result("youtube_verified", int(rec["youtube_verified"])))
    return {"results": results}


_WORD_RE = re.compile(r"[^\W\d_]+")
_POLISH_LETTERS = frozenset("ąćęłńóśźż")
# Frequent words that exist in only one of the two languages ("a", "i", "to" are left out).
_POLISH_WORDS = frozenset(
    [
        "się",
        "nie",
        "jest",
        "że",
        "na",
        "do",
        "dla",
        "jak",
        "po",
        "przy",
        "od",
        "tak",
        "już",
        "bardzo",
        "ale",
        "czy",
        "gdy",
        "kiedy",
        "aby",
        "jej",
        "jego",
        "sobie",
        "tym",
        "tej",
        "tego",
        "są",
        "będzie",
        "ci",
        "cię",
        "twój",
        "twoje",
        "twoją",
        "może",
        "który",
        "która",
        "które",
        "oraz",
        "ten",
        "ta",
        "tę",
        "co",
        "jeszcze",
        "chwilę",
        "dzień",
        "wieczór",
        "piosenka",
        "utwór",
    ]
)
_ENGLISH_WORDS = frozenset(
    [
        "the",
        "and",
        "of",
        "you",
        "your",
        "it",
        "is",
        "in",
        "for",
        "with",
        "this",
        "that",
        "on",
        "as",
        "be",
        "can",
        "will",
        "while",
        "its",
        "an",
        "at",
        "from",
        "into",
        "let",
        "so",
        "just",
        "more",
        "right",
        "are",
        "was",
        "what",
        "when",
        "song",
        "day",
        "evening",
        "without",
    ]
)


def detect_language(text: str) -> str | None:
    """'pl', 'en' or None: a deterministic heuristic for the two UI languages only."""
    lowered = text.lower()
    words = _WORD_RE.findall(lowered)
    polish = sum(w in _POLISH_WORDS for w in words) + 2 * sum(c in _POLISH_LETTERS for c in lowered)
    english = sum(w in _ENGLISH_WORDS for w in words)
    if polish == english:
        return None
    return "pl" if polish > english else "en"


def explanation_language(inputs: dict[str, Any], outputs: dict[str, Any]) -> Result:
    """FR-15: the user-facing texts are in the UI locale, whatever the input language."""
    if not _completed(outputs):
        return _result("explanation_language", None, "no recommendation")
    rec = outputs["recommendation"]
    detected = {
        "explanation": detect_language(rec["explanation"]),
        "need_summary": detect_language(rec["need_summary"]),
    }
    wrong = {field: lang for field, lang in detected.items() if lang != inputs["locale"]}
    comment = ", ".join(f"{f}: {lang or 'unknown'}" for f, lang in wrong.items()) or None
    return _result("explanation_language", int(not wrong), comment)


# --- LLM-as-judge ---


class FitVerdict(BaseModel):
    reasoning: str = Field(description="Step-by-step reasoning in English, before the scores.")
    energy: int = Field(ge=0, le=2, description="Intensity and tempo: 0 wrong, 1 partly, 2 right.")
    goal: int = Field(ge=0, le=2, description="Does what the music should do: 0, 1 or 2.")
    requests: int = Field(
        ge=0, le=2, description="Explicit requests and the avoid list: 0 ignored, 1 partly, 2 met."
    )
    specificity: int = Field(
        ge=0, le=2, description="0 a generic default, 1 fits some details, 2 chosen for this case."
    )
    weaknesses: str = Field(
        description='The reasons this is not a perfect pick, even small ones; "none" if none.'
    )
    profile_faithful: bool = Field(
        description="True if the Need Profile is a faithful reading of the description."
    )


FIT_ASPECTS = ("energy", "goal", "requests", "specificity")


def load_judge_prompt() -> PromptTemplate:
    return load_prompt("fit_judge", directory=JUDGE_PROMPTS_DIR)


def make_fit_judge(
    registry: ModelRegistry, tier: Tier, prompt: PromptTemplate
) -> Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, list[Result]]]]:
    async def fit(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, list[Result]]:
        if not _completed(outputs):
            return {
                "results": [
                    _result("fit", 0, "no recommendation"),
                    _result("profile_faithful", None),
                ]
            }
        rec = outputs["recommendation"]
        clarification = ""
        if outputs.get("clarified"):
            clarification = (
                f"<clarification>\nQuestion: {outputs.get('clarification_question')}\n"
                f"Answer: {outputs.get('clarification_answer')}\n</clarification>"
            )
        messages = prompt.render(
            description=inputs["text"],
            clarification=clarification,
            need_profile=json.dumps(outputs.get("need_profile"), ensure_ascii=False, indent=2),
            title=rec["title"],
            artist=rec["artist"],
            explanation=rec["explanation"],
        )
        verdict = (await structured_call(registry, tier, FitVerdict, messages)).value
        aspects = {name: getattr(verdict, name) for name in FIT_ASPECTS}
        total = sum(aspects.values())
        summary = ", ".join(f"{name} {score}" for name, score in aspects.items())
        return {
            "results": [
                _result(
                    "fit",
                    total / (2 * len(FIT_ASPECTS)),
                    f"{total}/8 ({summary}). Weaknesses: {verdict.weaknesses}\n{verdict.reasoning}",
                ),
                *(_result(f"fit_{name}", score / 2) for name, score in aspects.items()),
                _result("profile_faithful", int(verdict.profile_faithful)),
            ]
        }

    return fit


# --- Summary evaluator ---


def diversity(outputs: list[dict[str, Any]]) -> dict[str, list[Result]]:
    """How varied the songs are across the dataset; repeated ones are listed in the comment."""
    recs = [o["recommendation"] for o in outputs if _completed(o)]
    if not recs:
        return {"results": [_result("distinct_songs", None), _result("distinct_artists", None)]}
    songs = Counter(normalized_key(r["artist"], r["title"]) for r in recs)
    artists = Counter(normalize_artist(r["artist"]) for r in recs)
    repeated = ", ".join(f"{key} x{n}" for key, n in songs.most_common() if n > 1)
    repeated_artists = ", ".join(f"{key} x{n}" for key, n in artists.most_common() if n > 1)
    return {
        "results": [
            _result("distinct_songs", len(songs) / len(recs), repeated or None),
            _result("distinct_artists", len(artists) / len(recs), repeated_artists or None),
        ]
    }
