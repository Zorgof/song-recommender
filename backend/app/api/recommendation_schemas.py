"""Request and response schemas of the recommendation endpoints."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.agents.schemas import Locale, Recommendation
from app.db.models import InputMode

# FR-6: 3-2000 characters, counted after trimming whitespace.
DescriptionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)
]
# The raw transcript of a voice recording (at most 90 s of speech).
TranscriptText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
CommentText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Score = Literal["up", "down"]

SCORE_VALUES: dict[Score, int] = {"up": 1, "down": 0}


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: DescriptionText
    input_mode: InputMode = InputMode.TEXT
    locale: Locale
    # Voice input only: the transcript as returned by /api/transcriptions, before the user's
    # edits. It is recorded in the trace next to the submitted `text` (FR-40).
    transcript: TranscriptText | None = None

    @model_validator(mode="after")
    def _transcript_only_for_voice(self) -> Self:
        if self.transcript is not None and self.input_mode != InputMode.VOICE:
            raise ValueError("transcript is only allowed with input_mode 'voice'")
        return self


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: AnswerText


class CompletedResponse(BaseModel):
    status: Literal["completed"] = "completed"
    recommendation: Recommendation


class NeedsClarificationResponse(BaseModel):
    status: Literal["needs_clarification"] = "needs_clarification"
    request_id: str
    # In the UI locale.
    question: str


RecommendationResponse = Annotated[
    CompletedResponse | NeedsClarificationResponse, Field(discriminator="status")
]


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: Score
    comment: CommentText | None = None


class FeedbackOut(BaseModel):
    score: Score
    comment: str | None
    synced_to_langsmith: bool


class HistoryItem(BaseModel):
    request_id: str
    created_at: datetime
    locale: str
    input_mode: InputMode
    input_text: str
    clarification_question: str | None
    clarification_answer: str | None
    title: str | None
    artist: str | None
    album_art_url: str | None
    spotify_url: str | None
    spotify_track_id: str | None
    spotify_verified: bool
    youtube_url: str | None
    youtube_verified: bool
    explanation: str | None
    need_summary: str | None
    trace_url: str | None
    feedback: FeedbackOut | None


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    total: int
    limit: int
    offset: int
