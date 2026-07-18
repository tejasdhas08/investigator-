"""Builds the canonical CaseTimeline (Section 3.10) from database rows.

Used by Stage 3 (narrative), Stage 4 (Q&A), and export. With exclude_rejected=True,
human-rejected events are excluded so regenerated narratives and Q&A never re-assert
what an investigator rejected (Stage 5).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.person import Person
from app.models.suspect import SuspectMatchResult, SuspectReference
from app.models.timeline_event import TimelineEvent
from app.models.video import Video
from app.schemas.timeline import CaseTimeline


def build_timeline(db: Session, case: Case, exclude_rejected: bool = True) -> CaseTimeline:
    videos = db.execute(select(Video).where(Video.case_id == case.id, Video.upload_complete)).scalars().all()
    persons = db.execute(select(Person).where(Person.case_id == case.id).order_by(Person.label)).scalars().all()
    stmt = select(TimelineEvent).where(TimelineEvent.case_id == case.id).order_by(TimelineEvent.start_ms)
    if exclude_rejected:
        stmt = stmt.where(TimelineEvent.review_status != "rejected")
    events = db.execute(stmt).scalars().all()
    label_by_id = {p.id: p.label for p in persons}

    best_match_by_person: dict = {}
    for r, ref in db.execute(
        select(SuspectMatchResult, SuspectReference)
        .join(SuspectReference, SuspectMatchResult.suspect_reference_id == SuspectReference.id)
        .where(SuspectReference.case_id == case.id)
    ).all():
        if r.verdict == "no_match" or r.review_status == "rejected":
            continue
        cur = best_match_by_person.get(r.person_id)
        if cur is None or r.cosine_similarity > cur["cosine_similarity"]:
            best_match_by_person[r.person_id] = {
                "suspect_reference_id": str(ref.id),
                "display_name": ref.display_name,
                "verdict": r.verdict,
                "cosine_similarity": round(r.cosine_similarity, 4),
            }

    male = sum(1 for p in persons if p.gender_estimate == "male")
    female = sum(1 for p in persons if p.gender_estimate == "female")

    doc = {
        "schema_version": "1.0",
        "case_id": str(case.id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "videos": [
            {
                "video_id": str(v.id),
                "media_type": v.media_type,
                "original_filename": v.original_filename,
                "duration_ms": int(v.duration_seconds * 1000) if v.duration_seconds else None,
                "fps_sampled": v.fps_sampled or 1.0,
                "width": v.width or 0,
                "height": v.height or 0,
                "has_audio": v.has_audio,
                "quality_notes": v.quality_notes or [],
            }
            for v in videos
        ],
        "persons": [
            {
                "person_id": str(p.id),
                "label": p.label,
                "gender_estimate": p.gender_estimate,
                "gender_confidence": p.gender_confidence,
                "age_estimate_range": p.age_estimate_range,
                "appearance_description": p.appearance_description,
                "face_visible": p.face_visible,
                "detection_confidence_avg": p.detection_confidence_avg,
                "first_seen_ms": p.first_seen_ms or 0,
                "last_seen_ms": p.last_seen_ms or 0,
                "presence_intervals": p.presence_intervals
                or [{"video_id": str(p.first_seen_video_id or (videos[0].id if videos else "")),
                     "start_ms": p.first_seen_ms or 0, "end_ms": p.last_seen_ms or 0}],
                "suspect_match": best_match_by_person.get(p.id),
            }
            for p in persons
        ],
        "events": [
            {
                "event_id": str(e.id),
                "video_id": str(e.video_id),
                "event_type": e.event_type,
                "start_ms": e.start_ms,
                "end_ms": e.end_ms,
                "start_frame": e.start_frame,
                "end_frame": e.end_frame,
                "person_label": label_by_id.get(e.person_id),
                "target_person_label": label_by_id.get(e.target_person_id),
                "label": e.label,
                "description": e.description,
                "confidence": e.confidence,
                "is_suspicious": e.is_suspicious,
                "requires_human_review": e.requires_human_review,
                "object_class": e.object_class,
                "actor_direction": e.actor_direction,
                "bbox": e.bbox,
                "evidence_frame_s3_keys": e.evidence_frame_s3_keys or ["missing"],
            }
            for e in events
        ],
        "counts": {
            "persons_total": len(persons),
            "male": male,
            "female": female,
            "unknown_gender": len(persons) - male - female,
        },
    }
    return CaseTimeline.model_validate(doc)
