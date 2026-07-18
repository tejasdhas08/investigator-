import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index,
    Integer, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.types import GUID, JSONVariant

EVENT_TYPES = (
    "person_appearance", "person_exit", "action", "interaction",
    "object_detection", "suspicious_flag", "scene_change",
)


class TimelineEvent(Base):
    __tablename__ = "timeline_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('person_appearance','person_exit','action','interaction',"
            "'object_detection','suspicious_flag','scene_change')",
            name="ck_events_type",
        ),
        CheckConstraint(
            "review_status IN ('unreviewed','approved','rejected','edited')", name="ck_events_review"
        ),
        Index("ix_events_case_start", "case_id", "start_ms"),
        Index("ix_events_case_person", "case_id", "person_id"),
        Index("ix_events_case_suspicious", "case_id", "is_suspicious"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("cases.id", ondelete="CASCADE"))
    video_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("videos.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    person_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("persons.id", ondelete="CASCADE"))
    target_person_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("persons.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    bbox: Mapped[dict | None] = mapped_column(JSONVariant)
    object_class: Mapped[str | None] = mapped_column(Text)
    actor_direction: Mapped[str | None] = mapped_column(Text)  # 'person->target' | None (unclear)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(Text, default="unreviewed")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"))
    human_note: Mapped[str | None] = mapped_column(Text)
    evidence_frame_s3_keys: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
