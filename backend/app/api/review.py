"""Stage 5 review endpoints: event approve/reject/edit, narrative text edits, person overrides."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import get_db
from app.core.deps import get_case_for_user, get_current_user
from app.models.case import Case
from app.models.person import Person
from app.models.timeline_event import TimelineEvent
from app.models.user import User
from app.schemas.api import EventReviewRequest, NarrativeEditRequest, PersonOverrideRequest, TimelineEventOut
from app.services import audit

router = APIRouter(prefix="/cases/{case_id}", tags=["review"])

_ACTION_TO_STATUS = {"approve": "approved", "reject": "rejected", "edit": "edited"}


@router.post("/events/{event_id}/review", response_model=TimelineEventOut)
def review_event(
    event_id: uuid.UUID,
    body: EventReviewRequest,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.get(TimelineEvent, event_id)
    if event is None or event.case_id != case.id:
        raise HTTPException(404, detail={"error": "not_found", "message": "Event not found"})
    if body.action == "edit" and not body.human_note:
        raise HTTPException(422, detail={"error": "note_required", "message": "Edit requires human_note"})
    before = event.review_status
    event.review_status = _ACTION_TO_STATUS[body.action]
    event.reviewed_by = user.id
    if body.human_note is not None:
        event.human_note = body.human_note
    audit.log(db, action=f"claim.{event.review_status}", actor_user_id=user.id, case_id=case.id,
              entity_type="timeline_event", entity_id=event.id,
              detail={"before": before, "after": event.review_status, "human_note": body.human_note})
    db.commit()
    db.refresh(event)
    return TimelineEventOut.model_validate(event)


@router.post("/narrative/edits")
def edit_narrative(
    body: NarrativeEditRequest,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not case.narrative_json:
        raise HTTPException(404, detail={"error": "no_narrative", "message": "Narrative not generated yet"})
    doc = case.narrative_json
    original = _resolve_path(doc, body.path)
    if original is None:
        raise HTTPException(422, detail={"error": "bad_path", "message": f"Path '{body.path}' not found"})
    doc.setdefault("human_edits", []).append(
        {
            "path": body.path,
            "original_text": original,
            "edited_text": body.edited_text,
            "edited_by": str(user.id),
            "edited_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    case.narrative_json = doc
    flag_modified(case, "narrative_json")
    audit.log(db, action="claim.edited", actor_user_id=user.id, case_id=case.id,
              entity_type="narrative", entity_id=case.id,
              detail={"path": body.path, "original_text": original, "edited_text": body.edited_text})
    db.commit()
    return case.narrative_json


def _resolve_path(doc: dict, path: str) -> str | None:
    """Resolve 'narrative_sections[2].text' style paths; returns the string value or None."""
    import re

    node = doc
    for part in path.split("."):
        m = re.fullmatch(r"(\w+)(?:\[(\d+)\])?", part)
        if not m:
            return None
        key, idx = m.group(1), m.group(2)
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
        if idx is not None:
            if not isinstance(node, list) or int(idx) >= len(node):
                return None
            node = node[int(idx)]
    return node if isinstance(node, str) else None


@router.post("/persons/{person_id}/override")
def override_person(
    person_id: uuid.UUID,
    body: PersonOverrideRequest,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    person = db.get(Person, person_id)
    if person is None or person.case_id != case.id:
        raise HTTPException(404, detail={"error": "not_found", "message": "Person not found"})
    detail = {}
    if body.gender_estimate is not None:
        detail["gender_override"] = {"ai_value": person.gender_estimate, "human_value": body.gender_estimate}
        person.gender_human_override = body.gender_estimate
    if body.display_alias is not None:
        detail["display_alias"] = {"from": person.display_alias, "to": body.display_alias}
        person.display_alias = body.display_alias
    if detail:
        audit.log(db, action="claim.edited", actor_user_id=user.id, case_id=case.id,
                  entity_type="person", entity_id=person.id, detail=detail)
    db.commit()
    from app.schemas.api import PersonOut

    return PersonOut.model_validate(person)
