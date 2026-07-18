"""Persons, timeline, and narrative retrieval + narrative regeneration."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_case_for_user, get_current_user
from app.models.case import Case
from app.models.person import Person
from app.models.timeline_event import TimelineEvent
from app.models.user import User
from app.schemas.api import Page, PersonOut, TimelineEventOut
from app.services import storage

router = APIRouter(prefix="/cases/{case_id}", tags=["results"])


@router.get("/persons", response_model=list[PersonOut])
def list_persons(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    persons = db.execute(
        select(Person).where(Person.case_id == case.id).order_by(Person.label)
    ).scalars().all()
    out = []
    for p in persons:
        item = PersonOut.model_validate(p)
        item.face_crop_url = storage.presign_get(p.face_crop_s3_key)
        item.body_crop_url = storage.presign_get(p.body_crop_s3_key)
        out.append(item)
    return out


def _event_out(e: TimelineEvent, label_by_id: dict) -> TimelineEventOut:
    item = TimelineEventOut.model_validate(e)
    item.person_label = label_by_id.get(e.person_id)
    item.target_person_label = label_by_id.get(e.target_person_id)
    item.evidence_frame_urls = [u for u in (storage.presign_get(k) for k in (e.evidence_frame_s3_keys or [])) if u]
    return item


@router.get("/timeline", response_model=Page[TimelineEventOut])
def timeline(
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    person_label: str | None = None,
    event_type: str | None = None,
    suspicious_only: bool = False,
    from_ms: int | None = None,
    to_ms: int | None = None,
):
    persons = db.execute(select(Person).where(Person.case_id == case.id)).scalars().all()
    label_by_id = {p.id: p.label for p in persons}
    stmt = select(TimelineEvent).where(TimelineEvent.case_id == case.id)
    if person_label:
        pid = next((p.id for p in persons if p.label == person_label), None)
        if pid is None:
            raise HTTPException(404, detail={"error": "not_found", "message": "Unknown person label"})
        stmt = stmt.where(
            (TimelineEvent.person_id == pid) | (TimelineEvent.target_person_id == pid)
        )
    if event_type:
        stmt = stmt.where(TimelineEvent.event_type == event_type)
    if suspicious_only:
        stmt = stmt.where(TimelineEvent.is_suspicious.is_(True))
    if from_ms is not None:
        stmt = stmt.where(TimelineEvent.end_ms >= from_ms)
    if to_ms is not None:
        stmt = stmt.where(TimelineEvent.start_ms <= to_ms)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(TimelineEvent.start_ms).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return Page(items=[_event_out(e, label_by_id) for e in rows], total=total, page=page, page_size=page_size)


@router.get("/narrative")
def get_narrative(case: Case = Depends(get_case_for_user)):
    if not case.narrative_json:
        raise HTTPException(404, detail={"error": "no_narrative", "message": "Narrative not generated yet"})
    return case.narrative_json


@router.post("/narrative/regenerate", status_code=202)
def regenerate_narrative(
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if case.status not in ("complete", "failed"):
        raise HTTPException(409, detail={"error": "case_busy", "message": "Case is still processing"})
    case.status = "narrating"
    db.commit()
    from app.pipeline.tasks import enqueue_stage3

    enqueue_stage3(str(case.id))
    return {"job": "queued"}
