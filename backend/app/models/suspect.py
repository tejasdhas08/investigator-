import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.types import GUID, EmbeddingVector


class SuspectReference(Base):
    __tablename__ = "suspect_references"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("cases.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("users.id", ondelete="CASCADE"))
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    s3_key_photo: Mapped[str] = mapped_column(Text, nullable=False)
    face_embedding = mapped_column(EmbeddingVector(512), nullable=True)  # set at /complete validation
    face_detection_confidence: Mapped[float | None] = mapped_column(Float)
    upload_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    results = relationship("SuspectMatchResult", cascade="all, delete-orphan", backref="reference")


class SuspectMatchResult(Base):
    __tablename__ = "suspect_match_results"
    __table_args__ = (
        CheckConstraint("verdict IN ('match','possible_match','no_match')", name="ck_match_verdict"),
        CheckConstraint("review_status IN ('unreviewed','confirmed','rejected')", name="ck_match_review"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    suspect_reference_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("suspect_references.id", ondelete="CASCADE")
    )
    person_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("persons.id", ondelete="CASCADE"))
    cosine_similarity: Mapped[float] = mapped_column(Float, nullable=False)  # -1 == no usable face
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    best_frame_ms: Mapped[int | None] = mapped_column(BigInteger)
    comparison_face_s3_key: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(Text, default="unreviewed")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
