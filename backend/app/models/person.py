import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.types import GUID, EmbeddingVector, JSONVariant


class Person(Base):
    __tablename__ = "persons"
    __table_args__ = (
        UniqueConstraint("case_id", "label", name="uq_persons_case_label"),
        CheckConstraint("gender_estimate IN ('male','female','unknown')", name="ck_persons_gender"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("cases.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(Text, nullable=False)
    display_alias: Mapped[str | None] = mapped_column(Text)  # human-set, e.g. "A (victim)"
    track_ids: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)
    first_seen_ms: Mapped[int | None] = mapped_column(BigInteger)
    last_seen_ms: Mapped[int | None] = mapped_column(BigInteger)
    first_seen_video_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("videos.id", ondelete="SET NULL"))
    presence_intervals: Mapped[list | None] = mapped_column(JSONVariant)
    face_embedding = mapped_column(EmbeddingVector(512), nullable=True)
    face_crop_s3_key: Mapped[str | None] = mapped_column(Text)
    body_crop_s3_key: Mapped[str | None] = mapped_column(Text)
    face_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    gender_estimate: Mapped[str] = mapped_column(Text, default="unknown")
    gender_confidence: Mapped[float | None] = mapped_column(Float)
    gender_human_override: Mapped[str | None] = mapped_column(Text)  # both values kept (Stage 5)
    age_estimate_range: Mapped[str | None] = mapped_column(Text)
    detection_confidence_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    appearance_description: Mapped[str | None] = mapped_column(Text)
    activity_summary: Mapped[str | None] = mapped_column(Text)
    is_suspect_match: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case = relationship("Case", back_populates="persons")
