import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_case_for_user, get_current_user, require_role
from app.models.case import Case, CaseMember
from app.models.user import User
from app.schemas.api import CaseCreate, CaseListItem, CaseOut, CasePatch, CaseStatusOut, Page
from app.services import audit, progress

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CaseOut, status_code=201)
def create_case(body: CaseCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    exists = db.execute(select(Case).where(Case.case_number == body.case_number)).scalar_one_or_none()
    if exists:
        raise HTTPException(409, detail={"error": "duplicate_case_number", "message": "Case number already exists"})
    case = Case(
        case_number=body.case_number,
        title=body.title,
        context_description=body.context_description,
        owner_id=user.id,
        status="created",
        retention_expires_at=datetime.now(timezone.utc) + timedelta(days=settings.retention_days),
    )
    db.add(case)
    db.flush()
    db.add(CaseMember(case_id=case.id, user_id=user.id, role_in_case="owner"))
    audit.log(db, action="case.create", actor_user_id=user.id, case_id=case.id,
              entity_type="case", entity_id=case.id, detail={"case_number": body.case_number})
    db.commit()
    db.refresh(case)
    return case


@router.get("", response_model=Page[CaseListItem])
def list_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = None,
    q: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Case)
    if user.role == "investigator":
        member_ids = select(CaseMember.case_id).where(CaseMember.user_id == user.id)
        stmt = stmt.where(or_(Case.owner_id == user.id, Case.id.in_(member_ids)))
    if status:
        stmt = stmt.where(Case.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Case.title.ilike(like), Case.case_number.ilike(like)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(Case.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return Page(items=rows, total=total, page=page, page_size=page_size)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case: Case = Depends(get_case_for_user)):
    return case


@router.patch("/{case_id}", response_model=CaseOut)
def patch_case(
    body: CasePatch,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changes = {}
    if body.title is not None:
        changes["title"] = {"from": case.title, "to": body.title}
        case.title = body.title
    if body.context_description is not None:
        changes["context_description"] = {"from": case.context_description, "to": body.context_description}
        case.context_description = body.context_description
    if changes:
        audit.log(db, action="case.update", actor_user_id=user.id, case_id=case.id,
                  entity_type="case", entity_id=case.id, detail=changes)
    db.commit()
    db.refresh(case)
    return case


@router.delete("/{case_id}", status_code=204)
def delete_case(
    hard: bool = Query(False),
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if hard:
        if user.role != "admin":
            raise HTTPException(403, detail={"error": "forbidden", "message": "Hard delete requires admin"})
        from app.services.retention import purge_case

        audit.log(db, action="case.deleted", actor_user_id=user.id, case_id=case.id,
                  detail={"mode": "hard", "case_number": case.case_number})
        purge_case(db, case, actor_user_id=user.id)
        db.commit()
        return
    case.status = "archived"
    audit.log(db, action="case.deleted", actor_user_id=user.id, case_id=case.id, detail={"mode": "archive"})
    db.commit()


@router.get("/{case_id}/status", response_model=CaseStatusOut)
def case_status(case: Case = Depends(get_case_for_user)):
    prog = progress.get_progress(str(case.id)) or {}
    return CaseStatusOut(
        status=case.status,
        stage=prog.get("stage"),
        stage_progress_pct=prog.get("pct"),
        failure_reason=case.failure_reason,
    )
