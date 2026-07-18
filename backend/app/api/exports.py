import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_case_for_user, get_current_user
from app.models.case import Case
from app.models.export import ExportReport
from app.models.user import User
from app.schemas.api import ExportCreateRequest, ExportOut
from app.services import audit, storage

router = APIRouter(prefix="/cases/{case_id}/exports", tags=["exports"])


@router.post("", status_code=202)
def create_export(
    body: ExportCreateRequest,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if case.status != "complete":
        raise HTTPException(409, detail={"error": "case_not_ready",
                                         "message": "Export requires completed analysis"})
    export = ExportReport(case_id=case.id, generated_by=user.id, includes_chat=body.includes_chat)
    db.add(export)
    db.flush()
    audit.log(db, action="export.generated", actor_user_id=user.id, case_id=case.id,
              entity_type="export_report", entity_id=export.id,
              detail={"includes_chat": body.includes_chat})
    db.commit()
    from app.pipeline.tasks import enqueue_export

    enqueue_export(str(export.id))
    return {"export_id": str(export.id)}


@router.get("", response_model=list[ExportOut])
def list_exports(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    return db.execute(
        select(ExportReport).where(ExportReport.case_id == case.id).order_by(ExportReport.created_at.desc())
    ).scalars().all()


@router.get("/{export_id}/download")
def download_export(
    export_id: uuid.UUID,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    export = db.get(ExportReport, export_id)
    if export is None or export.case_id != case.id:
        raise HTTPException(404, detail={"error": "not_found", "message": "Export not found"})
    if export.status != "complete" or not export.s3_key_pdf:
        raise HTTPException(409, detail={"error": "export_pending", "message": "Export not ready"})
    audit.log(db, action="export.downloaded", actor_user_id=user.id, case_id=case.id,
              entity_type="export_report", entity_id=export.id, detail={"sha256": export.sha256})
    db.commit()
    return RedirectResponse(storage.presign_get(export.s3_key_pdf), status_code=302)
