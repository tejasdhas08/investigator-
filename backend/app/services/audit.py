"""Append-only, hash-chained audit log (ARCHITECTURE.md 3.9 / 7.4).

Each row stores prev_row_sha256 = sha256(canonical(previous row) || canonical(this row's detail)).
verify_chain() recomputes the chain and reports the first broken row, if any.
"""
import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog

GENESIS = "0" * 64


def _canonical_row(row: AuditLog) -> str:
    return json.dumps(
        {
            "id": row.id,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            "actor_type": row.actor_type,
            "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
            "case_id": str(row.case_id) if row.case_id else None,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id) if row.entity_id else None,
            "detail": row.detail,
            "prev_row_sha256": row.prev_row_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _chain_hash(prev_row: AuditLog | None, detail: dict) -> str:
    prev = _canonical_row(prev_row) if prev_row is not None else GENESIS
    payload = prev + json.dumps(detail, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def log(
    db: Session,
    *,
    action: str,
    actor_type: str = "user",
    actor_user_id: uuid.UUID | None = None,
    case_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    detail: dict | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    detail = detail or {}
    prev_row = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    row = AuditLog(
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        case_id=case_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail,
        ip_address=ip_address,
        prev_row_sha256=_chain_hash(prev_row, detail),
    )
    db.add(row)
    db.flush()
    return row


def ai_claim(
    db: Session,
    *,
    case_id: uuid.UUID,
    claim_text: str,
    claim_type: str,
    cited_event_ids: list[str],
    confidences: list[float],
    model_id: str,
    prompt_sha256: str,
    timeline_sha256: str,
) -> AuditLog:
    """Required fields for every AI-generated claim (Section 7.4)."""
    return log(
        db,
        action="ai.claim.created",
        actor_type="ai",
        case_id=case_id,
        detail={
            "claim_text": claim_text,
            "claim_type": claim_type,
            "cited_event_ids": cited_event_ids,
            "confidences": confidences,
            "model_id": model_id,
            "prompt_sha256": prompt_sha256,
            "timeline_sha256": timeline_sha256,
        },
    )


def verify_chain(db: Session) -> tuple[bool, int | None]:
    """Returns (ok, first_broken_row_id)."""
    prev: AuditLog | None = None
    for row in db.execute(select(AuditLog).order_by(AuditLog.id.asc())).scalars():
        if row.prev_row_sha256 != _chain_hash(prev, row.detail):
            return False, row.id
        prev = row
    return True, None
