"""Phase 3 fake detector (PIPELINE_FAKE=1): loads the hand-authored fixture timeline
so the full UI, Stage 3, Q&A, review, and export can be built and tested with no GPU.
"""
import json
import pathlib
import uuid

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.case import Case
from app.models.person import Person
from app.models.suspect import SuspectMatchResult, SuspectReference
from app.models.timeline_event import TimelineEvent
from app.models.video import Video
from app.pipeline import thresholds as T
from app.services import audit, progress, timeline_builder

FIXTURE = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "timeline_fixture.json"


def run(case_id: str) -> None:
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        case.status = "detecting"
        db.commit()
        progress.set_progress(case_id, "detecting", 10)

        video = db.execute(
            select(Video).where(Video.case_id == case.id, Video.upload_complete)
        ).scalars().first()
        if video is None:
            raise RuntimeError("no ingested media")
        fixture = json.loads(FIXTURE.read_text())

        persons_by_label = {}
        for p in fixture["persons"]:
            person = Person(
                case_id=case.id,
                label=p["label"],
                track_ids=[{"video_id": str(video.id), "tracker_track_id": ord(p["label"][0])}],
                first_seen_ms=p["first_seen_ms"],
                last_seen_ms=p["last_seen_ms"],
                first_seen_video_id=video.id,
                presence_intervals=[{"video_id": str(video.id),
                                     "start_ms": p["first_seen_ms"], "end_ms": p["last_seen_ms"]}],
                face_visible=p["face_visible"],
                face_crop_s3_key=(f"{video.s3_prefix_frames}000000.jpg" if p["face_visible"] else None),
                body_crop_s3_key=f"{video.s3_prefix_frames}000000.jpg",
                gender_estimate=p["gender_estimate"],
                gender_confidence=p["gender_confidence"],
                age_estimate_range=p["age_estimate_range"],
                detection_confidence_avg=p["detection_confidence_avg"],
                appearance_description=p["appearance_description"],
            )
            db.add(person)
            persons_by_label[p["label"]] = person
        db.flush()

        fps = video.fps_sampled or 5.0
        for e in fixture["events"]:
            frame = int(e["start_ms"] / 1000 * fps)
            end_frame = int(e["end_ms"] / 1000 * fps)
            db.add(TimelineEvent(
                case_id=case.id,
                video_id=video.id,
                event_type=e["event_type"],
                start_ms=e["start_ms"],
                end_ms=e["end_ms"],
                start_frame=frame,
                end_frame=end_frame,
                person_id=persons_by_label[e["person_label"]].id if e.get("person_label") else None,
                target_person_id=(
                    persons_by_label[e["target_person_label"]].id if e.get("target_person_label") else None
                ),
                label=e["label"],
                description=e.get("description"),
                confidence=e["confidence"],
                bbox=e.get("bbox"),
                object_class=e.get("object_class"),
                actor_direction=e.get("actor_direction"),
                is_suspicious=e.get("is_suspicious", False),
                requires_human_review=e.get("requires_human_review", False),
                evidence_frame_s3_keys=[f"{video.s3_prefix_frames}{min(frame, (video.frame_count_sampled or 1) - 1):06d}.jpg"],
            ))

        _update_counts(db, case)
        # match any reference photos uploaded before processing (mirrors real stage2)
        for ref in db.execute(
            select(SuspectReference).where(SuspectReference.case_id == case.id,
                                           SuspectReference.upload_complete)
        ).scalars():
            _fake_match(db, case, ref)
        timeline = timeline_builder.build_timeline(db, case, exclude_rejected=False)
        _upload_timeline(case, timeline)
        audit.log(db, action="pipeline.stage2.complete", actor_type="system", case_id=case.id,
                  detail={"mode": "fake", "persons": len(persons_by_label)})
        case.status = "narrating"
        db.commit()
        progress.set_progress(case_id, "detecting", 100)


def match_suspect(case_id: str, ref_id: str) -> None:
    with SessionLocal() as db:
        ref = db.get(SuspectReference, ref_id)
        case = db.get(Case, case_id)
        if ref is None or case is None:
            return
        _fake_match(db, case, ref)
        db.commit()


def _fake_match(db, case: Case, ref: SuspectReference) -> None:
    """Fake matching: Person A scores as a match, others no_match; a reference whose
    display_name contains 'noface' simulates the no-face-detected rejection."""
    if "noface" in ref.display_name.lower():
        audit.log(db, action="suspect.match.computed", actor_type="system", case_id=case.id,
                  entity_type="suspect_reference", entity_id=ref.id,
                  detail={"error": "no_face_detected"})
        return
    ref.face_detection_confidence = 0.98
    ref.face_embedding = [0.0] * 512
    persons = db.execute(select(Person).where(Person.case_id == case.id)).scalars().all()
    existing = {
        r.person_id for r in db.execute(
            select(SuspectMatchResult).where(SuspectMatchResult.suspect_reference_id == ref.id)
        ).scalars()
    }
    for p in persons:
        if p.id in existing:
            continue
        if not p.face_visible:
            sim, verdict = -1.0, "no_match"
        elif p.label == "A":
            sim, verdict = 0.71, "match"
        else:
            sim, verdict = 0.31, "no_match"
        db.add(SuspectMatchResult(
            suspect_reference_id=ref.id, person_id=p.id,
            cosine_similarity=sim, verdict=verdict,
            best_frame_ms=p.first_seen_ms, comparison_face_s3_key=p.face_crop_s3_key,
        ))
        audit.log(db, action="suspect.match.computed", actor_type="ai", case_id=case.id,
                  entity_type="suspect_reference", entity_id=ref.id,
                  detail={"person_label": p.label, "cosine_similarity": sim, "verdict": verdict})


def _update_counts(db, case: Case) -> None:
    persons = db.execute(select(Person).where(Person.case_id == case.id)).scalars().all()
    case.person_count_total = len(persons)
    case.person_count_male = sum(1 for p in persons if p.gender_estimate == "male")
    case.person_count_female = sum(1 for p in persons if p.gender_estimate == "female")
    case.person_count_unknown_gender = sum(1 for p in persons if p.gender_estimate == "unknown")


def _upload_timeline(case: Case, timeline) -> None:
    from app.services import storage

    try:
        storage.upload_bytes(
            timeline.model_dump_json().encode(), f"cases/{case.id}/timeline.json", "application/json"
        )
    except Exception:
        pass  # canonical copy lives in the DB; the S3 copy is a convenience artifact
