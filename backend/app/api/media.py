import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_case_for_user, get_current_user
from app.models.case import Case
from app.models.user import User
from app.models.video import Video
from app.schemas.api import MediaCompleteRequest, MediaUploadRequest, MediaUploadResponse, VideoOut
from app.services import audit, storage

router = APIRouter(prefix="/cases/{case_id}/media", tags=["media"])

_EXT_BY_TYPE = {"video": {"mp4", "mov", "avi", "mkv", "webm"}, "photo": {"jpg", "jpeg", "png", "heic"}}


@router.post("", response_model=MediaUploadResponse)
def request_upload(
    body: MediaUploadRequest,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if case.status not in ("created", "uploading"):
        raise HTTPException(409, detail={"error": "case_not_uploadable",
                                         "message": f"Case status is '{case.status}'"})
    count = db.execute(select(func.count()).select_from(Video).where(Video.case_id == case.id)).scalar_one()
    if count >= settings.max_media_per_case:
        raise HTTPException(422, detail={"error": "too_many_files",
                                         "message": f"Max {settings.max_media_per_case} media files per case"})
    if body.size_bytes > settings.max_upload_bytes:
        raise HTTPException(422, detail={"error": "file_too_large", "message": "Max 4 GB per file"})
    ext = body.filename.rsplit(".", 1)[-1].lower() if "." in body.filename else ""
    if ext not in _EXT_BY_TYPE[body.media_type]:
        raise HTTPException(422, detail={"error": "unsupported_extension",
                                         "message": f"Extension .{ext} not allowed for {body.media_type}"})
    dup = db.execute(
        select(Video).where(Video.case_id == case.id, Video.sha256 == body.sha256)
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(409, detail={"error": "duplicate_media", "message": "Identical file already uploaded"})

    video = Video(
        case_id=case.id,
        media_type=body.media_type,
        original_filename=body.filename,
        sha256=body.sha256,
        s3_key_original="",
    )
    db.add(video)
    db.flush()
    key = f"cases/{case.id}/media/{video.id}/original.{ext}"
    video.s3_key_original = key
    case.status = "uploading"
    audit.log(db, action="media.upload", actor_user_id=user.id, case_id=case.id,
              entity_type="video", entity_id=video.id,
              detail={"filename": body.filename, "sha256": body.sha256, "size_bytes": body.size_bytes})
    db.commit()
    return MediaUploadResponse(
        video_id=video.id, upload_url=storage.presign_put(key, body.content_type), s3_key=key
    )


@router.post("/{video_id}/complete")
def complete_upload(
    video_id: uuid.UUID,
    body: MediaCompleteRequest,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None or video.case_id != case.id:
        raise HTTPException(404, detail={"error": "not_found", "message": "Media not found"})
    if not storage.object_exists(video.s3_key_original):
        raise HTTPException(409, detail={"error": "upload_incomplete",
                                         "message": "Object not found in storage — upload did not finish"})
    video.upload_complete = True

    if body.start_processing:
        incomplete = db.execute(
            select(func.count()).select_from(Video).where(
                Video.case_id == case.id, Video.upload_complete.is_(False), Video.id != video.id
            )
        ).scalar_one()
        if incomplete:
            raise HTTPException(409, detail={"error": "uploads_pending",
                                             "message": "Other files are still uploading"})
        case.status = "queued"
        db.commit()
        from app.pipeline.tasks import start_case_pipeline

        start_case_pipeline(str(case.id))
        return {"status": "queued"}
    db.commit()
    return {"status": "uploaded"}


@router.get("", response_model=list[VideoOut])
def list_media(
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    videos = db.execute(select(Video).where(Video.case_id == case.id)).scalars().all()
    out = []
    for v in videos:
        item = VideoOut.model_validate(v)
        item.stream_url = storage.presign_get(v.s3_key_normalized or v.s3_key_original)
        out.append(item)
        audit.log(db, action="media.view", actor_user_id=user.id, case_id=case.id,
                  entity_type="video", entity_id=v.id, detail={})
    db.commit()
    return out
