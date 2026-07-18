import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_case_for_user, get_current_user
from app.models.case import Case
from app.models.person import Person
from app.models.suspect import SuspectMatchResult, SuspectReference
from app.models.user import User
from app.schemas.api import (
    MatchReviewRequest, SuspectCreateRequest, SuspectCreateResponse,
    SuspectMatchResultOut, SuspectReferenceOut,
)
from app.services import audit, storage

router = APIRouter(prefix="/cases/{case_id}/suspects", tags=["suspects"])


@router.post("", response_model=SuspectCreateResponse)
def create_reference(
    body: SuspectCreateRequest,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ref = SuspectReference(
        case_id=case.id, uploaded_by=user.id, display_name=body.display_name, s3_key_photo=""
    )
    db.add(ref)
    db.flush()
    ext = body.filename.rsplit(".", 1)[-1].lower() if "." in body.filename else "jpg"
    key = f"cases/{case.id}/suspects/{ref.id}/reference.{ext}"
    ref.s3_key_photo = key
    audit.log(db, action="media.upload", actor_user_id=user.id, case_id=case.id,
              entity_type="suspect_reference", entity_id=ref.id,
              detail={"display_name": body.display_name, "sha256": body.sha256})
    db.commit()
    return SuspectCreateResponse(
        suspect_reference_id=ref.id, upload_url=storage.presign_put(key, body.content_type)
    )


@router.post("/{ref_id}/complete", status_code=202)
def complete_reference(
    ref_id: uuid.UUID,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ref = db.get(SuspectReference, ref_id)
    if ref is None or ref.case_id != case.id:
        raise HTTPException(404, detail={"error": "not_found", "message": "Reference not found"})
    if not storage.object_exists(ref.s3_key_photo):
        raise HTTPException(409, detail={"error": "upload_incomplete",
                                         "message": "Photo not found in storage"})
    ref.upload_complete = True
    db.commit()
    from app.pipeline.tasks import enqueue_suspect_match

    # Validates the face and computes matches; 422 no_face_detected surfaces via match results/status.
    enqueue_suspect_match(str(case.id), str(ref.id))
    return {"status": "matching_queued"}


@router.get("", response_model=list[SuspectReferenceOut])
def list_references(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    refs = db.execute(select(SuspectReference).where(SuspectReference.case_id == case.id)).scalars().all()
    persons = {p.id: p for p in db.execute(select(Person).where(Person.case_id == case.id)).scalars()}
    out = []
    for ref in refs:
        results = db.execute(
            select(SuspectMatchResult)
            .where(SuspectMatchResult.suspect_reference_id == ref.id)
            .order_by(SuspectMatchResult.cosine_similarity.desc())
        ).scalars().all()
        items = []
        for r in results:
            item = SuspectMatchResultOut.model_validate(r)
            p = persons.get(r.person_id)
            item.person_label = p.label if p else None
            item.comparison_face_url = storage.presign_get(r.comparison_face_s3_key)
            items.append(item)
        out.append(SuspectReferenceOut(
            id=ref.id, display_name=ref.display_name,
            photo_url=storage.presign_get(ref.s3_key_photo), results=items,
        ))
    return out


@router.post("/{ref_id}/results/{result_id}/review", response_model=SuspectMatchResultOut)
def review_match(
    ref_id: uuid.UUID,
    result_id: uuid.UUID,
    body: MatchReviewRequest,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = db.get(SuspectMatchResult, result_id)
    if result is None or result.suspect_reference_id != ref_id:
        raise HTTPException(404, detail={"error": "not_found", "message": "Match result not found"})
    result.review_status = "confirmed" if body.action == "confirm" else "rejected"
    result.reviewed_by = user.id
    person = db.get(Person, result.person_id)
    if person is not None:
        person.is_suspect_match = result.review_status == "confirmed" and result.verdict in ("match", "possible_match")
    audit.log(db, action="suspect.match.confirmed" if body.action == "confirm" else "claim.rejected",
              actor_user_id=user.id, case_id=case.id,
              entity_type="suspect_match_result", entity_id=result.id,
              detail={"verdict": result.verdict, "cosine_similarity": result.cosine_similarity,
                      "action": body.action})
    db.commit()
    db.refresh(result)
    out = SuspectMatchResultOut.model_validate(result)
    out.person_label = person.label if person else None
    return out
