import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_case_for_user, require_role
from app.models.audit import AuditLog
from app.models.case import Case

router = APIRouter(tags=["audit"])


def _serialize(row: AuditLog) -> dict:
    return {
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
    }


def _page(db: Session, stmt, page: int, page_size: int):
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    return {"items": [_serialize(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/cases/{case_id}/audit", dependencies=[Depends(require_role("supervisor", "admin"))])
def case_audit(
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: str | None = None,
):
    stmt = select(AuditLog).where(AuditLog.case_id == case.id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return _page(db, stmt, page, page_size)


@router.get("/audit", dependencies=[Depends(require_role("supervisor", "admin"))])
def global_audit(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: str | None = None,
    actor_user_id: uuid.UUID | None = None,
):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    return _page(db, stmt, page, page_size)
