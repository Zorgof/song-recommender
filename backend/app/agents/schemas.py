"""Structured outputs of the agents and the final recommendation (implementation plan, 2.2).

Field descriptions are part of the JSON schema sent to the model, so every score states its scale
and direction explicitly (the light model read "energy" backwards without it; see ADR-02).
Reasoning fields are in English; only the fields named `*_localized`, `clarification_question`
and `explanation` are in the UI locale.
"""

from typing import Literal

from pydantic import BaseModel, Field

Locale = Literal["en", "pl"]
Goal = Literal["match", "uplift", "calm", "energize", "focus", "comfort", "release"]

LOCALE_NAMES: dict[str, str] = {"en": "English", "pl": "Polish"}


class RouterClassification(BaseModel):
    """Light-model classification of a request the heuristics could not decide."""

    complexity: Literal["simple", "complex"] = Field(
        description=(
            "simple: one clear mood and situation. complex: mixed, conflicting or unclear "
            "feelings, or a situation that needs careful reasoning."
        )
    )
    reason: str = Field(description="One short sentence in English explaining the choice.")


class NeedProfile(BaseModel):
    summary: str = Field(description="One-sentence restatement of the user's need, in English.")
    summary_localized: str = Field(
        description="The same sentence in the UI language, addressed to the user."
    )
    emotions: list[str] = Field(
        description='Emotions the user expresses, in English, e.g. ["tired", "quietly hopeful"].'
    )
    energy: float = Field(
        ge=0, le=1, description="The user's current energy: 0 = exhausted, 1 = very energetic."
    )
    valence: float = Field(
        ge=0, le=1, description="The user's current mood: 0 = very negative, 1 = very positive."
    )
    day_context: str = Field(description="What the day looks like and what comes next, in English.")
    goal: Goal = Field(
        description=(
            "What the music should do: match (mirror the mood), uplift (raise the mood), "
            "calm (lower tension), energize (raise energy), focus (support concentration), "
            "comfort (console), release (let emotions out)."
        )
    )
    target_energy: float = Field(
        ge=0, le=1, description="Energy the music should have: 0 = very quiet, 1 = very intense."
    )
    musical_hints: list[str] = Field(
        description="Genres, tempo, vocals or instrumental, language of lyrics; in English."
    )
    avoid: list[str] = Field(description="What the music should avoid, in English.")
    confidence: float = Field(
        ge=0, le=1, description="How sure you are of this profile: 0 = guessing, 1 = certain."
    )
    needs_clarification: bool = Field(
        description="True only if the description is too vague to choose music for."
    )
    clarification_question: str | None = Field(
        description="If needs_clarification: one short question in the UI language; else null."
    )
    rationale: str = Field(description="Your reasoning behind this profile, in English.")


class SongCandidate(BaseModel):
    rank: int = Field(ge=1, description="1 = best fit.")
    title: str = Field(description="Song title as published, without version suffixes.")
    artist: str = Field(description="Main artist as published.")
    rationale: str = Field(description="Why the song fits the Need Profile, in English.")
    explanation: str = Field(
        description="2-3 sentences for the user, in the UI language: why this song, now."
    )
    fit_notes: str = Field(
        description="How the song's energy, mood and character match the profile, in English."
    )


class CuratorOutput(BaseModel):
    candidates: list[SongCandidate] = Field(
        min_length=1, max_length=10, description="Ranked song candidates, best first."
    )


class Recommendation(BaseModel):
    """The final result returned to the client."""

    request_id: str
    locale: Locale
    title: str
    artist: str
    album_art_url: str | None
    spotify_url: str
    # Used by the frontend for the embed iframe.
    spotify_track_id: str | None
    youtube_url: str
    spotify_verified: bool
    youtube_verified: bool
    # In the UI locale.
    explanation: str
    need_summary: str
    trace_url: str | None = None
