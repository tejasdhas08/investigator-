"""Stage 2 "lite": real detection for CPU-only / restricted-network deployments.

Every output of this backend is genuine inference on the uploaded frames — nothing is
canned. It exists because the full backend (stage2.py: YOLOv8 + InsightFace) needs model
weights hosted on github.com / huggingface.co, which restricted networks (including the
hosted dev environment this was built in) block. This backend only needs:

  - dlib face detection + 128-d face embeddings — weights ship INSIDE the
    `face-recognition-models` wheel from PyPI (no runtime downloads at all)
  - MediaPipe EfficientDet-Lite0 (COCO-80) for person + object detection — a single
    .tflite file fetched from storage.googleapis.com by scripts/fetch_models.py
  - norfair for tracking (pure Python, no weights)

Honest capability gaps versus the full backend — reported, never faked:
  - Gender estimation: every open gender model is hosted on blocked infrastructure, so
    persons are emitted as gender 'unknown' with a `gender_model_unavailable` quality
    note. The unknown bucket is already first-class in the UI/counts/narrative.
  - Weapons: limited to COCO's weapon-adjacent classes (knife, scissors, baseball bat).
    No firearm model — noted as `firearm_model_unavailable` so narratives can caveat it.
  - Appearance description: no CLIP; a plain colour histogram note is used instead.

Suspect matching uses dlib's metric (euclidean distance on 128-d embeddings; same-person
guidance < 0.6). We store similarity = 1 - distance in the existing cosine_similarity
column and keep the strictly "algorithmic similarity" framing.
"""
import math
import pathlib
import shutil
import tempfile
import uuid
from collections import defaultdict

import numpy as np
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.case import Case
from app.models.person import Person
from app.models.suspect import SuspectMatchResult, SuspectReference
from app.models.timeline_event import TimelineEvent
from app.models.video import Video
from app.pipeline import thresholds as T
from app.pipeline.stage2 import (
    Track,
    _attach_objects_to_persons,
    _detect_interactions,
    _emit_person_events,
    _labels,
    _suspicious_flags,
    _tracks_overlap_in_time,
    _update_counts,
)
from app.services import audit, progress, storage, timeline_builder

MODELS_DIR = pathlib.Path(__file__).resolve().parents[3] / "models"
OBJECT_MODEL = MODELS_DIR / "efficientdet_lite0.tflite"

LITE_COCO_CLASSES = {
    "knife", "scissors", "baseball bat", "backpack", "handbag", "bottle",
    "cell phone", "car", "truck",
}
LITE_WEAPON_CLASSES = {"knife", "scissors", "baseball bat"}


def available() -> tuple[bool, str]:
    try:
        import face_recognition  # noqa: F401
        import mediapipe  # noqa: F401
        import norfair  # noqa: F401
    except ImportError as exc:
        return False, f"missing python package: {exc.name}"
    if not OBJECT_MODEL.exists():
        return False, f"object model missing: {OBJECT_MODEL} (run scripts/fetch_models.py)"
    return True, "ok"


_detector = None


def _object_detector():
    global _detector
    if _detector is None:
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        options = vision.ObjectDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(OBJECT_MODEL)),
            score_threshold=min(T.WEAPON_DET_CONF, 0.30),
            max_results=25,
        )
        _detector = vision.ObjectDetector.create_from_options(options)
    return _detector


def run(case_id: str) -> None:
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        case.status = "detecting"
        db.commit()
        progress.set_progress(case_id, "detecting", 0)

        videos = db.execute(
            select(Video).where(Video.case_id == case.id, Video.upload_complete)
        ).scalars().all()

        all_tracks: list[Track] = []
        object_events: list[dict] = []
        for vi, video in enumerate(videos):
            notes = set(video.quality_notes or [])
            notes.update({"gender_model_unavailable", "firearm_model_unavailable"})
            video.quality_notes = sorted(notes)
            tracks, objs = _process_video(db, case, video,
                                          base_pct=int(vi / max(len(videos), 1) * 80),
                                          span_pct=int(80 / max(len(videos), 1)))
            all_tracks += tracks
            object_events += objs
            db.commit()

        progress.set_progress(case_id, "detecting", 82)
        persons = _merge_tracks_to_persons(db, case, videos, all_tracks)
        progress.set_progress(case_id, "detecting", 90)
        _emit_person_events(db, case, videos, persons)
        _attach_objects_to_persons(db, case, object_events, persons)
        _detect_interactions(db, case, videos, persons)
        _suspicious_flags(db, case, videos, persons)
        _update_counts(db, case)

        for ref in db.execute(
            select(SuspectReference).where(SuspectReference.case_id == case.id,
                                           SuspectReference.upload_complete)
        ).scalars():
            _match_reference(db, case, ref)

        timeline = timeline_builder.build_timeline(db, case, exclude_rejected=False)
        storage.upload_bytes(timeline.model_dump_json().encode(),
                             f"cases/{case.id}/timeline.json", "application/json")
        audit.log(db, action="pipeline.stage2.complete", actor_type="system", case_id=case.id,
                  detail={"backend": "lite", "persons": len(persons), "tracks": len(all_tracks)})
        case.status = "narrating"
        db.commit()
        progress.set_progress(case_id, "detecting", 100)


# ------------------------------------------------------------- per-video pass

def _process_video(db, case, video: Video, base_pct: int, span_pct: int):
    import cv2
    import face_recognition
    import mediapipe as mp
    from norfair import Detection, Tracker

    detector = _object_detector()
    tracker = Tracker(
        distance_function="iou",
        distance_threshold=0.7,
        initialization_delay=0,   # photos are 1 frame; emit tracks immediately
        hit_counter_max=int((video.fps_sampled or 5.0) * 2),
    )
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="csai-lite-"))
    tracks: dict[int, Track] = {}
    object_events: list[dict] = []
    scene_cut_frames = {
        e.start_frame for e in db.execute(
            select(TimelineEvent).where(TimelineEvent.video_id == video.id,
                                        TimelineEvent.event_type == "scene_change")
        ).scalars()
    }

    try:
        n = video.frame_count_sampled or 0
        for idx in range(n):
            key = f"{video.s3_prefix_frames}{idx:06d}.jpg"
            local = workdir / "frame.jpg"
            try:
                storage.download_file(key, str(local))
                frame_bgr = cv2.imread(str(local))
                if frame_bgr is None:
                    continue
            except Exception:
                continue
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

            if idx in scene_cut_frames:
                tracker = Tracker(distance_function="iou", distance_threshold=0.7,
                                  initialization_delay=0,
                                  hit_counter_max=int((video.fps_sampled or 5.0) * 2))

            # --- real object + person detection (EfficientDet-Lite0, COCO-80) ---
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            person_boxes: list[tuple[tuple, float]] = []
            for det in result.detections:
                cat = det.categories[0]
                name = (cat.category_name or "").lower()
                b = det.bounding_box
                box = (b.origin_x, b.origin_y, b.origin_x + b.width, b.origin_y + b.height)
                if name == "person" and cat.score >= T.PERSON_DET_CONF:
                    person_boxes.append((box, float(cat.score)))
                elif name in LITE_COCO_CLASSES:
                    is_weapon = name in LITE_WEAPON_CLASSES
                    floor = T.WEAPON_DET_CONF if is_weapon else T.OBJECT_DET_CONF
                    if cat.score >= floor:
                        object_events.append(_object_event(video, idx, name, float(cat.score),
                                                           box, is_weapon))

            # --- real face detection (dlib HOG) ---
            faces = face_recognition.face_locations(rgb, model="hog")
            # promote faces with no covering person box to person detections, so
            # head-and-shoulders footage still yields tracked persons
            for (top, right, bottom, left) in faces:
                if not any(x1 <= (left + right) / 2 <= x2 and y1 <= (top + bottom) / 2 <= y2
                           for (x1, y1, x2, y2), _ in person_boxes):
                    fh = bottom - top
                    person_boxes.append((
                        (max(left - fh, 0), max(top - fh // 2, 0),
                         min(right + fh, rgb.shape[1]), min(bottom + fh * 4, rgb.shape[0])),
                        0.60,  # conservative synthetic-box confidence, review band
                    ))

            detections = [
                Detection(points=np.array([[x1, y1], [x2, y2]]), scores=np.array([s, s]))
                for (x1, y1, x2, y2), s in person_boxes
            ]
            tracked = tracker.update(detections=detections)

            for tobj in tracked:
                if tobj.last_detection is None:
                    continue
                pts = tobj.last_detection.points
                score = float(tobj.last_detection.scores[0])
                x1, y1 = int(pts[0][0]), int(pts[0][1])
                x2, y2 = int(pts[1][0]), int(pts[1][1])
                tr = tracks.setdefault(int(tobj.id), Track(track_id=int(tobj.id),
                                                           video_id=str(video.id)))
                tr.frames.append(idx)
                tr.boxes.append((x1, y1, x2, y2))
                tr.confs.append(score)

                body = frame_bgr[max(y1, 0):y2, max(x1, 0):x2]
                if body.size and (tr.best_body_crop is None or score > tr.best_body_crop[0]):
                    ok, buf = cv2.imencode(".jpg", body)
                    if ok:
                        tr.best_body_crop = (score, idx, buf.tobytes())

                # attach faces whose centre lies in this track's box; encode + REAL crop
                for (top, right, bottom, left) in faces:
                    cx, cy = (left + right) / 2, (top + bottom) / 2
                    if not (x1 <= cx <= x2 and y1 <= cy <= y2):
                        continue
                    encs = face_recognition.face_encodings(
                        rgb, known_face_locations=[(top, right, bottom, left)], num_jitters=1)
                    if not encs:
                        continue
                    quality = float((right - left) * (bottom - top))
                    pad = (bottom - top) // 4
                    crop = frame_bgr[max(top - pad, 0):bottom + pad,
                                     max(left - pad, 0):right + pad]
                    ok, fbuf = cv2.imencode(".jpg", crop) if crop.size else (False, None)
                    tr.faces.append((
                        quality,
                        encs[0].astype(float).tolist(),
                        "unknown",          # no gender model available offline (see module docstring)
                        0.0,
                        None,
                        idx,
                        fbuf.tobytes() if ok else None,
                    ))

            if idx % 10 == 0:
                progress.set_progress(str(case.id), "detecting",
                                      base_pct + int(idx / max(n, 1) * span_pct))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return list(tracks.values()), object_events


def _object_event(video, idx, cname, conf, box, is_weapon) -> dict:
    w, h = video.width or 1, video.height or 1
    x1, y1, x2, y2 = box
    return {
        "video_id": video.id, "frame": idx,
        "ms": int(idx / (video.fps_sampled or 5.0) * 1000),
        "object_class": cname, "confidence": conf, "is_weapon": is_weapon,
        "bbox": {"x": x1 / w, "y": y1 / h, "w": (x2 - x1) / w, "h": (y2 - y1) / h},
        "frame_key": f"{video.s3_prefix_frames}{idx:06d}.jpg",
    }


# ------------------------------------------------- merge tracks -> persons (dlib metric)

def _dlib_distance(a, b) -> float:
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b)))


def _merge_tracks_to_persons(db, case, videos, tracks: list[Track]) -> list[Person]:
    tracks = [t for t in tracks if t.frames]
    tracks.sort(key=lambda t: -len(t.frames))
    tracks = tracks[:T.MAX_TRACKED_PERSONS]

    groups: list[list[Track]] = []
    for tr in tracks:
        emb = tr.best_faces(1)[0][1] if tr.faces else None
        placed = False
        for g in groups:
            if any(_tracks_overlap_in_time(tr, other) for other in g):
                continue  # provably different people
            g_emb = next((o.best_faces(1)[0][1] for o in g if o.faces), None)
            if emb is not None and g_emb is not None and \
                    _dlib_distance(emb, g_emb) <= T.LITE_REID_MAX_DIST:
                g.append(tr)
                placed = True
                break
        if not placed:
            groups.append([tr])

    fps_by_vid = {str(v.id): (v.fps_sampled or 5.0) for v in videos}
    persons: list[Person] = []
    label_gen = _labels()
    groups.sort(key=lambda g: min(min(t.frames) for t in g))
    for g in groups:
        label = next(label_gen)
        all_faces = [f for t in g for f in t.faces]
        best_face = max(all_faces, key=lambda f: f[0]) if all_faces else None

        intervals = []
        for t in g:
            fps = fps_by_vid.get(t.video_id, 5.0)
            intervals.append({"video_id": t.video_id,
                              "start_ms": int(min(t.frames) / fps * 1000),
                              "end_ms": int(max(t.frames) / fps * 1000)})
        first = min(intervals, key=lambda i: i["start_ms"])

        person = Person(
            case_id=case.id, label=label,
            track_ids=[{"video_id": t.video_id, "tracker_track_id": t.track_id} for t in g],
            first_seen_ms=first["start_ms"],
            last_seen_ms=max(i["end_ms"] for i in intervals),
            first_seen_video_id=uuid.UUID(first["video_id"]),
            presence_intervals=intervals,
            face_visible=best_face is not None,
            face_embedding=(np.pad(np.asarray(best_face[1]), (0, 512 - 128)).tolist()
                            if best_face else None),  # 128-d dlib vec stored in 512-d column
            gender_estimate="unknown",          # honest: no gender model in lite backend
            gender_confidence=None,
            age_estimate_range=None,
            detection_confidence_avg=float(np.mean([c for t in g for c in t.confs])),
            appearance_description=_appearance_note(g),
        )
        db.add(person)
        db.flush()
        if best_face and best_face[6]:
            key = f"cases/{case.id}/persons/{person.id}/face.jpg"
            storage.upload_bytes(best_face[6], key, "image/jpeg")
            person.face_crop_s3_key = key
        body = max((t.best_body_crop for t in g if t.best_body_crop), default=None,
                   key=lambda b: b[0] if b else -1)
        if body:
            key = f"cases/{case.id}/persons/{person.id}/body.jpg"
            storage.upload_bytes(body[2], key, "image/jpeg")
            person.body_crop_s3_key = key
        person._tracks = g
        persons.append(person)
    db.commit()
    return persons


def _appearance_note(tracks: list[Track]) -> str | None:
    """Dominant-colour note from the best body crop — a weak, honest signal only."""
    try:
        import cv2

        body = max((t.best_body_crop for t in tracks if t.best_body_crop), default=None,
                   key=lambda b: b[0] if b else -1)
        if body is None:
            return None
        img = cv2.imdecode(np.frombuffer(body[2], np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        v_mean = float(hsv[..., 2].mean())
        s_mean = float(hsv[..., 1].mean())
        if v_mean < 70:
            return "predominantly dark clothing (colour-histogram estimate)"
        if v_mean > 180 and s_mean < 60:
            return "predominantly light clothing (colour-histogram estimate)"
        hue = float(np.median(hsv[..., 0]))
        name = ("red" if hue < 10 or hue >= 170 else
                "orange/yellow" if hue < 33 else
                "green" if hue < 78 else
                "blue" if hue < 131 else "purple/pink")
        return f"predominantly {name} tones in clothing (colour-histogram estimate)"
    except Exception:
        return None


# ------------------------------------------------------------- suspect matching

def match_suspect(case_id: str, ref_id: str) -> None:
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        ref = db.get(SuspectReference, ref_id)
        if case is None or ref is None:
            return
        _match_reference(db, case, ref)
        db.commit()


def _match_reference(db, case, ref: SuspectReference) -> None:
    import cv2
    import face_recognition

    if ref.face_embedding is None:
        data = storage.get_bytes(ref.s3_key_photo)
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            faces = []
        else:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            locs = face_recognition.face_locations(rgb, model="hog")
            faces = face_recognition.face_encodings(rgb, known_face_locations=locs)
        if not faces:
            audit.log(db, action="suspect.match.computed", actor_type="system", case_id=case.id,
                      entity_type="suspect_reference", entity_id=ref.id,
                      detail={"error": "no_face_detected", "backend": "lite"})
            return
        ref.face_embedding = np.pad(faces[0].astype(float), (0, 512 - 128)).tolist()
        ref.face_detection_confidence = 0.90  # dlib HOG has no calibrated score; fixed conservative value

    ref_vec = np.asarray(ref.face_embedding)[:128]
    persons = db.execute(select(Person).where(Person.case_id == case.id)).scalars().all()
    for p in persons:
        existing = db.execute(
            select(SuspectMatchResult).where(SuspectMatchResult.suspect_reference_id == ref.id,
                                             SuspectMatchResult.person_id == p.id)
        ).scalar_one_or_none()
        if existing:
            continue
        if p.face_embedding is None:
            sim, verdict = -1.0, "no_match"
        else:
            dist = _dlib_distance(ref_vec, np.asarray(p.face_embedding)[:128])
            sim = max(0.0, 1.0 - dist)
            if dist <= T.LITE_MATCH_MAX_DIST:
                verdict = "match"
            elif dist <= T.LITE_POSSIBLE_MAX_DIST:
                verdict = "possible_match"
            else:
                verdict = "no_match"
        db.add(SuspectMatchResult(
            suspect_reference_id=ref.id, person_id=p.id,
            cosine_similarity=round(sim, 4), verdict=verdict,
            best_frame_ms=p.first_seen_ms, comparison_face_s3_key=p.face_crop_s3_key,
        ))
        audit.log(db, action="suspect.match.computed", actor_type="ai", case_id=case.id,
                  entity_type="suspect_reference", entity_id=ref.id,
                  detail={"person_label": p.label, "similarity": round(sim, 4),
                          "verdict": verdict, "backend": "lite",
                          "metric": "dlib_euclidean_1minus"})
