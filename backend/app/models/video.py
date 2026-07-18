import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.types import GUID, JSONVariant


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (CheckConstraint("media_type IN ('video','photo')", name="ck_videos_media_type"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("cases.id", ondelete="CASCADE"))
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    s3_key_original: Mapped[str] = mapped_column(Text, nullable=False)
    s3_key_normalized: Mapped[str | None] = mapped_column(Text)
    s3_prefix_frames: Mapped[str | None] = mapped_column(Text)
    s3_key_audio: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    fps_original: Mapped[float | None] = mapped_column(Float)
    fps_sampled: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    frame_count_sampled: Mapped[int | None] = mapped_column(Integer)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_notes: Mapped[list | None] = mapped_column(JSONVariant)
    upload_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case = relationship("Case", back_populates="videos")
