from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.types import GUID, JSONVariant


class AuditLog(Base):
    """Append-only. The application role must have INSERT/SELECT only (see deploy/init-db.sql).
    Rows are chained via prev_row_sha256 for tamper evidence (Section 3.9)."""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user','system','ai')", name="ck_audit_actor"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id = mapped_column(GUID, nullable=True)
    case_id = mapped_column(GUID, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id = mapped_column(GUID, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONVariant, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(Text)
    prev_row_sha256: Mapped[str] = mapped_column(Text, nullable=False)
