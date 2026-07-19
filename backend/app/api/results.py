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


@router.get("/events/{event_id}/explain")
def explain_event(
    event_id: uuid.UUID,
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """Explainability drill-down (Phase 3): the signals behind an event's confidence
    score. Everything returned is derived from stored detection data — no new claims."""
    e = db.get(TimelineEvent, event_id)
    if e is None or e.case_id != case.id:
        raise HTTPException(404, detail={"error": "not_found", "message": "Event not found"})
    persons = {p.id: p for p in db.execute(select(Person).where(Person.case_id == case.id)).scalars()}
    signals = []
    signals.append({"label": "Detection model confidence", "value": round(e.confidence, 3),
                    "detail": f"Backend score for the '{e.label}' {e.event_type.replace('_', ' ')}."})
    band = ("high (>=0.70): shown as a standard claim" if e.confidence >= 0.70 else
            "review band (0.40-0.69): flagged for human review" if e.confidence >= 0.40 else
            "below threshold (<0.40): not used as a claim")
    signals.append({"label": "Confidence band", "value": band, "detail": None})
    if e.person_id and e.person_id in persons:
        p = persons[e.person_id]
        signals.append({"label": "Subject track confidence",
                        "value": round(p.detection_confidence_avg, 3),
                        "detail": f"Mean detection confidence for Person {p.label} across the video."})
        signals.append({"label": "Face visible for subject", "value": p.face_visible,
                        "detail": "Face-based identity signals are only available when a face was seen."})
    if e.event_type == "interaction":
        signals.append({
            "label": "Actor direction resolved", "value": bool(e.actor_direction),
            "detail": ("Approach-speed difference exceeded threshold, so an actor was inferred."
                       if e.actor_direction else
                       "Approach speeds were too similar — who initiated cannot be established."),
        })
        signals.append({"label": "Confidence cap", "value": 0.75,
                        "detail": "Interaction confidence is capped: the pipeline never claims "
                                  "near-certainty about intent from pixels."})
    if e.object_class:
        signals.append({"label": "Object class", "value": e.object_class,
                        "detail": "COCO/weapon detector class label for the detected object."})
    signals.append({"label": "Evidence frames", "value": len(e.evidence_frame_s3_keys or []),
                    "detail": "Number of representative frames stored as visual evidence."})
    return {
        "event_id": str(e.id),
        "confidence": e.confidence,
        "requires_human_review": e.requires_human_review,
        "review_status": e.review_status,
        "signals": signals,
    }


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
