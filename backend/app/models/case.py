import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.types import GUID, JSONVariant

CASE_STATUSES = (
    "created", "uploading", "queued", "ingesting", "detecting", "narrating",
    "complete", "failed", "archived",
)


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created','uploading','queued','ingesting','detecting','narrating',"
            "'complete','failed','archived')",
            name="ck_cases_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    case_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    context_description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="created")
    failure_reason: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("users.id", ondelete="CASCADE"))
    narrative_json: Mapped[dict | None] = mapped_column(JSONVariant)
    narrative_model: Mapped[str | None] = mapped_column(Text)
    narrative_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    person_count_total: Mapped[int | None] = mapped_column(Integer)
    person_count_male: Mapped[int | None] = mapped_column(Integer)
    person_count_female: Mapped[int | None] = mapped_column(Integer)
    person_count_unknown_gender: Mapped[int | None] = mapped_column(Integer)
    retention_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    videos = relationship("Video", back_populates="case", cascade="all, delete-orphan")
    persons = relationship("Person", back_populates="case", cascade="all, delete-orphan")
    members = relationship("CaseMember", cascade="all, delete-orphan")


class CaseMember(Base):
    __tablename__ = "case_members"
    __table_args__ = (
        CheckConstraint("role_in_case IN ('owner','collaborator','viewer')", name="ck_case_members_role"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_in_case: Mapped[str] = mapped_column(Text, nullable=False, default="collaborator")
