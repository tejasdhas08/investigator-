"""Retention enforcement (Section 7.3): nightly purge of cases past retention_expires_at.
Hard purge deletes all S3 objects (media, frames, crops, embeddings live in DB rows which
cascade) and DB rows; the audit trail persists (contains no media)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.case import Case
from app.services import audit, storage


def purge_case(db: Session, case: Case, actor_user_id: uuid.UUID | None = None) -> None:
    deleted = storage.delete_prefix(f"cases/{case.id}/")
    audit.log(db, action="retention.purge", actor_type="system" if actor_user_id is None else "user",
              actor_user_id=actor_user_id, case_id=case.id,
              detail={"case_number": case.case_number, "s3_objects_deleted": deleted})
    db.delete(case)  # cascades to videos/persons/events/chat/suspects/exports


def purge_expired() -> int:
    now = datetime.now(timezone.utc)
    purged = 0
    with SessionLocal() as db:
        expired = db.execute(select(Case).where(Case.retention_expires_at < now)).scalars().all()
        for case in expired:
            purge_case(db, case)
            purged += 1
        db.commit()
    return purged
