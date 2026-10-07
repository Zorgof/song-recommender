"""ORM models. See docs/implementation-plan.md, section 2.5."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Enum, ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utc_now


class InputMode(StrEnum):
    TEXT = "text"
    VOICE = "voice"


class RecommendationStatus(StrEnum):
    PENDING = "pending"
    NEEDS_CLARIFICATION = "needs_clarification"
    COMPLETED = "completed"
    FAILED = "failed"


def _str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    # VARCHAR + CHECK constraint storing the enum *values*; portable and readable in SQLite.
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )


class Recommendation(Base):
    """One recommendation request; its id is also the LangSmith root run id."""

    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, index=True)
    status: Mapped[RecommendationStatus] = mapped_column(
        _str_enum(RecommendationStatus, "recommendation_status"),
        default=RecommendationStatus.PENDING,
    )
    locale: Mapped[str] = mapped_column(String(5))
    input_mode: Mapped[InputMode] = mapped_column(_str_enum(InputMode, "input_mode"))
    input_text: Mapped[str] = mapped_column(Text)
    clarification_question: Mapped[str | None] = mapped_column(Text)
    clarification_answer: Mapped[str | None] = mapped_column(Text)
    need_profile: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Chosen track; empty until the recommendation is completed.
    title: Mapped[str | None] = mapped_column(String(500))
    artist: Mapped[str | None] = mapped_column(String(500))
    album_art_url: Mapped[str | None] = mapped_column(String(1000))
    spotify_track_id: Mapped[str | None] = mapped_column(String(64), index=True)
    spotify_url: Mapped[str | None] = mapped_column(String(1000))
    spotify_verified: Mapped[bool] = mapped_column(default=False)
    youtube_url: Mapped[str | None] = mapped_column(String(1000))
    youtube_verified: Mapped[bool] = mapped_column(default=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    need_summary: Mapped[str | None] = mapped_column(Text)

    # Observability: models per tier, escalation flag, error code of a failed run.
    models_used: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    escalated: Mapped[bool] = mapped_column(default=False)
    error_code: Mapped[str | None] = mapped_column(String(64))

    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan", passive_deletes=True
    )


class Feedback(Base):
    """User rating of a recommendation, mirrored to LangSmith as run feedback."""

    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("score IN (0, 1)", name="score_binary"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"), index=True
    )
    # 1 = thumbs up, 0 = thumbs down
    score: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    synced_to_langsmith: Mapped[bool] = mapped_column(default=False)

    recommendation: Mapped[Recommendation] = relationship(back_populates="feedback")


class TrackLinkCache(Base):
    """Catalog lookups per normalized "artist|title", to save Spotify calls and YouTube quota."""

    __tablename__ = "track_link_cache"

    normalized_key: Mapped[str] = mapped_column(String(1000), primary_key=True)

    # Spotify result; all empty when the track was searched but not found.
    spotify_track_id: Mapped[str | None] = mapped_column(String(64))
    spotify_url: Mapped[str | None] = mapped_column(String(1000))
    spotify_title: Mapped[str | None] = mapped_column(String(500))
    spotify_artist: Mapped[str | None] = mapped_column(String(500))
    album_art_url: Mapped[str | None] = mapped_column(String(1000))
    spotify_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # YouTube result; youtube_fetched_at set + video id empty means "searched, nothing found".
    youtube_video_id: Mapped[str | None] = mapped_column(String(32))
    youtube_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
