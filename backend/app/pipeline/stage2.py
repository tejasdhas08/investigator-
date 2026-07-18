"""Stage 2 (real): detection, tracking, attributes, objects, suspect matching.

Runs on the GPU worker (queue 'gpu'). Models per ARCHITECTURE.md Stage 2:
YOLOv8m (persons + COCO objects) + optional fine-tuned weapons model, ByteTrack,
InsightFace buffalo_l (SCRFD faces + ArcFace embeddings + genderage), OpenCLIP
zero-shot appearance/action refinement. All thresholds come from thresholds.py.
"""
import math
import pathlib
import shutil
import tempfile
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.case import Case
from app.models.person import Person
from app.models.suspect import SuspectMatchResult, SuspectReference
from app.models.timeline_event import TimelineEvent
from app.models.video import Video
from app.pipeline import thresholds as T
from app.services import audit, progress, storage, timeline_builder

MODELS_DIR = pathlib.Path(__file__).resolve().parents[3] / "models"


# ---------------------------------------------------------------- model loading

_models: dict = {}


def _load_models():
    if _models:
        return _models
    from ultralytics import YOLO

    _models["yolo"] = YOLO(str(MODELS_DIR / "yolov8m.pt"))
    weapons_path = MODELS_DIR / "weapons_yolov8m.pt"
    _models["weapons"] = YOLO(str(weapons_path)) if weapons_path.exists() else None

    from insightface.app import FaceAnalysis

    fa = FaceAnalysis(name="buffalo_l", root=str(MODELS_DIR / "insightface"))
    fa.prepare(ctx_id=0, det_thresh=T.FACE_DET_CONF)
    _models["faces"] = fa
    return _models


# ---------------------------------------------------------------- track state

@dataclass
class Track:
    track_id: int
    video_id: str
    frames: list[int] = field(default_factory=list)          # sampled frame indices
    boxes: list[tuple] = field(default_factory=list)         # (x1,y1,x2,y2) px
    confs: list[float] = field(default_factory=list)
    faces: list[tuple] = field(default_factory=list)         # (quality, embedding, gender, gender_conf, age, frame_idx, crop)
    best_body_crop: tuple | None = None                      # (conf, frame_idx, crop_bytes)

    def best_faces(self, k=3):
        return sorted(self.faces, key=lambda f: -f[0])[:k]


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
        frame_errors = 0
        for vi, video in enumerate(videos):
            tracks, objs, errs = _process_video(db, case, video,
                                                base_pct=int(vi / max(len(videos), 1) * 80))
            all_tracks += tracks
            object_events += objs
            frame_errors += errs

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
                  detail={"persons": len(persons), "tracks": len(all_tracks),
                          "frame_errors": frame_errors})
        case.status = "narrating"
        db.commit()
        progress.set_progress(case_id, "detecting", 100)


# ---------------------------------------------------------------- per-video pass

def _process_video(db, case, video: Video, base_pct: int):
    import cv2

    models = _load_models()
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="csai-stage2-"))
    tracks: dict[int, Track] = {}
    object_events: list[dict] = []
    errors = 0

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
            local = workdir / f"{idx:06d}.jpg"
            try:
                storage.download_file(key, str(local))
                frame = cv2.imread(str(local))
                if frame is None:
                    raise ValueError("unreadable frame")
            except Exception:
                errors += 1
                continue

            persist = idx not in scene_cut_frames  # reset tracker at cuts
            results = models["yolo"].track(
                frame, persist=persist, tracker="bytetrack.yaml",
                conf=T.PERSON_DET_CONF, verbose=False,
            )[0]
            _collect_person_boxes(results, idx, str(video.id), frame, tracks, models)
            object_events += _collect_objects(results, models, frame, idx, video)

            if idx % 25 == 0:
                progress.set_progress(str(case.id), "detecting",
                                      base_pct + int(idx / max(n, 1) * (80 / 1)))
            local.unlink(missing_ok=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if errors > 0.05 * max(video.frame_count_sampled or 1, 1):
        video.quality_notes = (video.quality_notes or []) + ["frame_processing_errors"]
        db.commit()
    return list(tracks.values()), object_events, errors


def _collect_person_boxes(results, idx, video_id, frame, tracks, models):
    import cv2

    if results.boxes is None or results.boxes.id is None:
        return
    names = results.names
    for box, cls, conf, tid in zip(
        results.boxes.xyxy.cpu().numpy(),
        results.boxes.cls.cpu().numpy(),
        results.boxes.conf.cpu().numpy(),
        results.boxes.id.cpu().numpy(),
    ):
        if names[int(cls)] != "person" or conf < T.PERSON_DET_CONF:
            continue
        tid = int(tid)
        tr = tracks.setdefault(tid, Track(track_id=tid, video_id=video_id))
        x1, y1, x2, y2 = box.astype(int)
        tr.frames.append(idx)
        tr.boxes.append((int(x1), int(y1), int(x2), int(y2)))
        tr.confs.append(float(conf))

        crop = frame[max(y1, 0):y2, max(x1, 0):x2]
        if crop.size and (tr.best_body_crop is None or conf > tr.best_body_crop[0]):
            ok, buf = cv2.imencode(".jpg", crop)
            if ok:
                tr.best_body_crop = (float(conf), idx, buf.tobytes())

        if crop.size:
            for face in models["faces"].get(crop):
                fw = face.bbox[2] - face.bbox[0]
                fh = face.bbox[3] - face.bbox[1]
                if min(fw, fh) < T.FACE_MIN_PX or face.det_score < T.FACE_DET_CONF:
                    continue
                quality = float(face.det_score) * float(fw * fh)
                fx1, fy1, fx2, fy2 = [int(v) for v in face.bbox]
                fcrop = crop[max(fy1, 0):fy2, max(fx1, 0):fx2]
                ok, fbuf = cv2.imencode(".jpg", fcrop) if fcrop.size else (False, None)
                gender = "male" if int(getattr(face, "gender", -1)) == 1 else "female"
                # insightface exposes no calibrated gender confidence; use det_score as proxy.
                tr.faces.append((
                    quality,
                    face.normed_embedding.astype(float).tolist(),
                    gender,
                    float(face.det_score),
                    int(getattr(face, "age", 0)) or None,
                    idx,
                    fbuf.tobytes() if ok else None,
                ))


def _collect_objects(results, models, frame, idx, video) -> list[dict]:
    out = []
    names = results.names
    if results.boxes is not None:
        for box, cls, conf in zip(
            results.boxes.xyxy.cpu().numpy(),
            results.boxes.cls.cpu().numpy(),
            results.boxes.conf.cpu().numpy(),
        ):
            cname = names[int(cls)]
            if cname == "person" or cname not in T.COCO_OBJECT_CLASSES:
                continue
            is_weapon = cname in T.WEAPON_CLASSES
            floor = T.WEAPON_DET_CONF if is_weapon else T.OBJECT_DET_CONF
            if conf < floor:
                continue
            out.append(_object_event(video, idx, cname, float(conf), box, is_weapon))
    if models["weapons"] is not None:
        wres = models["weapons"](frame, conf=T.WEAPON_DET_CONF, verbose=False)[0]
        if wres.boxes is not None:
            for box, cls, conf in zip(
                wres.boxes.xyxy.cpu().numpy(),
                wres.boxes.cls.cpu().numpy(),
                wres.boxes.conf.cpu().numpy(),
            ):
                out.append(_object_event(video, idx, wres.names[int(cls)], float(conf), box, True))
    return out


def _object_event(video, idx, cname, conf, box, is_weapon) -> dict:
    w, h = video.width or 1, video.height or 1
    x1, y1, x2, y2 = box
    ms = int(idx / (video.fps_sampled or 5.0) * 1000)
    return {
        "video_id": video.id, "frame": idx, "ms": ms, "object_class": cname,
        "confidence": conf, "is_weapon": is_weapon,
        "bbox": {"x": float(x1) / w, "y": float(y1) / h,
                 "w": float(x2 - x1) / w, "h": float(y2 - y1) / h},
        "frame_key": f"{video.s3_prefix_frames}{idx:06d}.jpg",
    }


# ------------------------------------------------------- merge tracks → persons

def _cos(a, b) -> float:
    a, b = np.asarray(a), np.asarray(b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else -1.0


def _labels():
    """A..Z, AA, AB, ..."""
    import itertools
    import string

    for size in itertools.count(1):
        for combo in itertools.product(string.ascii_uppercase, repeat=size):
            yield "".join(combo)


def _tracks_overlap_in_time(a: Track, b: Track) -> bool:
    return a.video_id == b.video_id and bool(set(a.frames) & set(b.frames))


def _merge_tracks_to_persons(db, case, videos, tracks: list[Track]) -> list[Person]:
    tracks = [t for t in tracks if t.frames]
    tracks.sort(key=lambda t: -len(t.frames))
    tracks = tracks[:T.MAX_TRACKED_PERSONS]

    groups: list[list[Track]] = []
    for tr in tracks:
        emb = tr.best_faces(1)[0][1] if tr.faces else None
        placed = False
        for g in groups:
            # never merge tracks that provably co-exist in the same frames
            if any(_tracks_overlap_in_time(tr, other) for other in g):
                continue
            g_emb = next((o.best_faces(1)[0][1] for o in g if o.faces), None)
            if emb is not None and g_emb is not None and _cos(emb, g_emb) >= T.REID_MERGE_COS:
                g.append(tr)
                placed = True
                break
        if not placed:
            groups.append([tr])

    fps_by_vid = {str(v.id): (v.fps_sampled or 5.0) for v in videos}
    vid_by_id = {str(v.id): v for v in videos}
    persons: list[Person] = []
    label_gen = _labels()
    groups.sort(key=lambda g: min(min(t.frames) for t in g))
    for g in groups:
        label = next(label_gen)
        all_faces = [f for t in g for f in t.faces]
        best_face = max(all_faces, key=lambda f: f[0]) if all_faces else None
        votes = defaultdict(float)
        for f in all_faces:
            votes[f[2]] += f[3]
        gender, gconf = "unknown", None
        if votes:
            gender = max(votes, key=votes.get)
            gconf = votes[gender] / sum(votes.values())
            if gconf < T.GENDER_CONF_MIN:
                gender = "unknown"
        ages = [f[4] for f in all_faces if f[4]]
        age_range = f"{max(min(ages) - 5, 0)}-{max(ages) + 5}" if ages else None

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
            face_embedding=best_face[1] if best_face else None,
            gender_estimate=gender, gender_confidence=gconf,
            age_estimate_range=age_range,
            detection_confidence_avg=float(np.mean([c for t in g for c in t.confs])),
            appearance_description=_appearance(g, vid_by_id),
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
        person._tracks = g  # transient, used by event emitters below
        persons.append(person)
    db.commit()
    return persons


def _appearance(tracks: list[Track], vid_by_id) -> str | None:
    """OpenCLIP zero-shot over the fixed attribute prompt bank; best-effort."""
    try:
        from app.pipeline.clip_attrs import describe_person

        body = max((t.best_body_crop for t in tracks if t.best_body_crop), default=None,
                   key=lambda b: b[0] if b else -1)
        return describe_person(body[2]) if body else None
    except Exception:
        return None


# ------------------------------------------------------------- event emission

def _ms(frame: int, fps: float) -> int:
    return int(frame / fps * 1000)


def _emit_person_events(db, case, videos, persons: list[Person]) -> None:
    fps_by_vid = {str(v.id): (v.fps_sampled or 5.0) for v in videos}
    frames_prefix = {str(v.id): v.s3_prefix_frames for v in videos}
    for person in persons:
        for tr in getattr(person, "_tracks", []):
            fps = fps_by_vid[tr.video_id]
            prefix = frames_prefix[tr.video_id]
            f0, f1 = min(tr.frames), max(tr.frames)
            conf = float(np.mean(tr.confs))
            db.add(TimelineEvent(
                case_id=case.id, video_id=uuid.UUID(tr.video_id), event_type="person_appearance",
                start_ms=_ms(f0, fps), end_ms=_ms(f0, fps), start_frame=f0, end_frame=f0,
                person_id=person.id, label="enters_frame",
                description=f"Person {person.label} enters frame", confidence=conf,
                requires_human_review=T.review_flag(conf),
                evidence_frame_s3_keys=[f"{prefix}{f0:06d}.jpg"],
            ))
            db.add(TimelineEvent(
                case_id=case.id, video_id=uuid.UUID(tr.video_id), event_type="person_exit",
                start_ms=_ms(f1, fps), end_ms=_ms(f1, fps), start_frame=f1, end_frame=f1,
                person_id=person.id, label="exits_frame",
                description=f"Person {person.label} exits frame", confidence=conf,
                requires_human_review=T.review_flag(conf),
                evidence_frame_s3_keys=[f"{prefix}{f1:06d}.jpg"],
            ))
            _emit_actions(db, case, person, tr, fps, prefix)
    db.commit()


def _speeds(tr: Track, fps: float) -> list[float]:
    """Centroid speed in person-widths/sec per step."""
    out = []
    for i in range(1, len(tr.frames)):
        (x1, y1, x2, y2), (px1, py1, px2, py2) = tr.boxes[i], tr.boxes[i - 1]
        w = max(x2 - x1, 1)
        dt = (tr.frames[i] - tr.frames[i - 1]) / fps
        if dt <= 0:
            out.append(0.0)
            continue
        dx = ((x1 + x2) / 2 - (px1 + px2) / 2) / w
        dy = ((y1 + y2) / 2 - (py1 + py2) / 2) / w
        out.append(math.hypot(dx, dy) / dt)
    return out


def _emit_actions(db, case, person: Person, tr: Track, fps: float, prefix: str) -> None:
    if len(tr.frames) < 2:
        return
    speeds = _speeds(tr, fps)
    labels = []
    for i, s in enumerate(speeds):
        x1, y1, x2, y2 = tr.boxes[i + 1]
        if (x2 - x1) > (y2 - y1):
            labels.append("lying_down")
        elif s > T.RUN_SPEED:
            labels.append("running")
        elif s > T.WALK_SPEED:
            labels.append("walking")
        else:
            labels.append("standing")
    # emit an event per label run
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            f0, f1 = tr.frames[start + 1], tr.frames[i]
            conf = float(np.mean(tr.confs[start + 1:i + 1]))
            label = labels[start]
            db.add(TimelineEvent(
                case_id=case.id, video_id=uuid.UUID(tr.video_id), event_type="action",
                start_ms=_ms(f0, fps), end_ms=_ms(f1, fps), start_frame=f0, end_frame=f1,
                person_id=person.id, label=label,
                description=f"Person {person.label} {label.replace('_', ' ')}",
                confidence=conf, requires_human_review=T.review_flag(conf),
                is_suspicious=False,
                bbox=_norm_bbox(tr.boxes[start + 1], case, tr, db),
                evidence_frame_s3_keys=[f"{prefix}{f0:06d}.jpg"],
            ))
            start = i


def _norm_bbox(box, case, tr, db) -> dict | None:
    video = db.get(Video, uuid.UUID(tr.video_id))
    if not video or not video.width or not video.height:
        return None
    x1, y1, x2, y2 = box
    return {"x": x1 / video.width, "y": y1 / video.height,
            "w": (x2 - x1) / video.width, "h": (y2 - y1) / video.height}


def _attach_objects_to_persons(db, case, object_events: list[dict], persons: list[Person]) -> None:
    """Group per-frame object hits into events; attach to nearest person when overlapping."""
    by_class: dict[tuple, list[dict]] = defaultdict(list)
    for o in object_events:
        by_class[(str(o["video_id"]), o["object_class"])].append(o)
    for (vid, cname), hits in by_class.items():
        hits.sort(key=lambda h: h["frame"])
        run_start = 0
        for i in range(1, len(hits) + 1):
            if i == len(hits) or hits[i]["frame"] - hits[i - 1]["frame"] > 10:
                seg = hits[run_start:i]
                conf = max(h["confidence"] for h in seg)
                is_weapon = seg[0]["is_weapon"]
                video = db.get(Video, seg[0]["video_id"])
                holder = _person_at(persons, vid, seg[0]["frame"], seg[0]["bbox"], video)
                db.add(TimelineEvent(
                    case_id=case.id, video_id=seg[0]["video_id"], event_type="object_detection",
                    start_ms=seg[0]["ms"], end_ms=seg[-1]["ms"],
                    start_frame=seg[0]["frame"], end_frame=seg[-1]["frame"],
                    person_id=holder.id if holder else None,
                    label="object_present", object_class=cname,
                    description=f"{cname} detected" + (f" near Person {holder.label}" if holder else ""),
                    confidence=conf,
                    is_suspicious=is_weapon,
                    requires_human_review=is_weapon and conf < T.WEAPON_REVIEW_BELOW or T.review_flag(conf),
                    bbox=seg[0]["bbox"],
                    evidence_frame_s3_keys=[seg[0]["frame_key"]],
                ))
                if is_weapon:
                    db.add(TimelineEvent(
                        case_id=case.id, video_id=seg[0]["video_id"], event_type="suspicious_flag",
                        start_ms=seg[0]["ms"], end_ms=seg[-1]["ms"],
                        start_frame=seg[0]["frame"], end_frame=seg[-1]["frame"],
                        person_id=holder.id if holder else None,
                        label="weapon_visible",
                        description=f"Possible {cname} visible",
                        confidence=conf, is_suspicious=True,
                        requires_human_review=conf < T.WEAPON_REVIEW_BELOW,
                        evidence_frame_s3_keys=[seg[0]["frame_key"]],
                    ))
                run_start = i
    db.commit()


def _person_at(persons, video_id: str, frame: int, bbox: dict, video) -> Person | None:
    if not video or not video.width:
        return None
    bx = (bbox["x"] + bbox["w"] / 2) * video.width
    by = (bbox["y"] + bbox["h"] / 2) * video.height
    best, best_d = None, 1e18
    for p in persons:
        for tr in getattr(p, "_tracks", []):
            if tr.video_id != video_id or frame not in tr.frames:
                continue
            x1, y1, x2, y2 = tr.boxes[tr.frames.index(frame)]
            if x1 - 20 <= bx <= x2 + 20 and y1 - 20 <= by <= y2 + 20:
                d = math.hypot(bx - (x1 + x2) / 2, by - (y1 + y2) / 2)
                if d < best_d:
                    best, best_d = p, d
    return best


def _detect_interactions(db, case, videos, persons: list[Person]) -> None:
    fps_by_vid = {str(v.id): (v.fps_sampled or 5.0) for v in videos}
    prefix_by_vid = {str(v.id): v.s3_prefix_frames for v in videos}
    for i, pa in enumerate(persons):
        for pb in persons[i + 1:]:
            for ta in getattr(pa, "_tracks", []):
                for tb in getattr(pb, "_tracks", []):
                    if ta.video_id != tb.video_id:
                        continue
                    _pair_interactions(db, case, pa, pb, ta, tb,
                                       fps_by_vid[ta.video_id], prefix_by_vid[ta.video_id])
    db.commit()


def _pair_interactions(db, case, pa, pb, ta: Track, tb: Track, fps: float, prefix: str) -> None:
    common = sorted(set(ta.frames) & set(tb.frames))
    if not common:
        return
    close_frames = []
    for f in common:
        ax1, ay1, ax2, ay2 = ta.boxes[ta.frames.index(f)]
        bx1, by1, bx2, by2 = tb.boxes[tb.frames.index(f)]
        width = max(ax2 - ax1, 1)
        dist = math.hypot((ax1 + ax2) / 2 - (bx1 + bx2) / 2, (ay1 + ay2) / 2 - (by1 + by2) / 2)
        overlap = not (ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1)
        if dist <= T.INTERACTION_PROXIMITY_WIDTHS * width or overlap:
            close_frames.append((f, overlap))
    if len(close_frames) / fps < T.INTERACTION_MIN_SECONDS:
        return

    f0, f1 = close_frames[0][0], close_frames[-1][0]
    any_overlap = any(o for _, o in close_frames)
    label = "physical_contact" if any_overlap else "close_approach"
    conf = min(T.INTERACTION_CONF_CAP,
               float(np.mean(ta.confs)) * 0.5 + float(np.mean(tb.confs)) * 0.5)

    direction = _actor_direction(ta, tb, f0, fps)
    desc = f"Persons {pa.label} and {pb.label}: {label.replace('_', ' ')}"
    if label == "physical_contact" and direction is None:
        desc += " (mutual/unclear initiation)"
    actor_dir = None
    person_id, target_id = pa.id, pb.id
    if direction == "a":
        actor_dir = "person->target"
    elif direction == "b":
        person_id, target_id = pb.id, pa.id
        actor_dir = "person->target"
        desc = f"Persons {pb.label} and {pa.label}: {label.replace('_', ' ')}"

    db.add(TimelineEvent(
        case_id=case.id, video_id=uuid.UUID(ta.video_id), event_type="interaction",
        start_ms=_ms(f0, fps), end_ms=_ms(f1, fps), start_frame=f0, end_frame=f1,
        person_id=person_id, target_person_id=target_id,
        label=label, description=desc, confidence=conf,
        actor_direction=actor_dir,
        is_suspicious=label == "physical_contact",
        requires_human_review=(label == "physical_contact" and actor_dir is None) or T.review_flag(conf),
        evidence_frame_s3_keys=[f"{prefix}{f0:06d}.jpg", f"{prefix}{f1:06d}.jpg"],
    ))


def _actor_direction(ta: Track, tb: Track, contact_frame: int, fps: float) -> str | None:
    """Actor = whoever approached faster in the ~1s before contact; None if <30% apart."""
    def approach_speed(tr: Track, other: Track) -> float:
        window = [f for f in tr.frames if contact_frame - fps <= f <= contact_frame]
        if len(window) < 2 or contact_frame not in other.frames:
            return 0.0
        ox1, oy1, ox2, oy2 = other.boxes[other.frames.index(contact_frame)]
        ocx, ocy = (ox1 + ox2) / 2, (oy1 + oy2) / 2

        def dist_at(f):
            x1, y1, x2, y2 = tr.boxes[tr.frames.index(f)]
            return math.hypot((x1 + x2) / 2 - ocx, (y1 + y2) / 2 - ocy)

        d0, d1 = dist_at(window[0]), dist_at(window[-1])
        dt = (window[-1] - window[0]) / fps
        return (d0 - d1) / dt if dt > 0 else 0.0

    sa, sb = approach_speed(ta, tb), approach_speed(tb, ta)
    if sa <= 0 and sb <= 0:
        return None
    hi, lo = max(sa, sb), max(min(sa, sb), 1e-6)
    if hi / lo < T.ACTOR_DIRECTION_SPEED_RATIO:
        return None
    return "a" if sa > sb else "b"


def _suspicious_flags(db, case, videos, persons: list[Person]) -> None:
    fps_by_vid = {str(v.id): (v.fps_sampled or 5.0) for v in videos}
    dims = {str(v.id): (v.width or 1, v.height or 1) for v in videos}
    prefix_by_vid = {str(v.id): v.s3_prefix_frames for v in videos}
    for person in persons:
        for tr in getattr(person, "_tracks", []):
            fps = fps_by_vid[tr.video_id]
            w, h = dims[tr.video_id]
            # loitering: bounding region of centroids stays within 10% of frame for >120s
            duration = (max(tr.frames) - min(tr.frames)) / fps
            if duration >= T.LOITER_SECONDS:
                cxs = [(b[0] + b[2]) / 2 / w for b in tr.boxes]
                cys = [(b[1] + b[3]) / 2 / h for b in tr.boxes]
                if (max(cxs) - min(cxs)) < T.LOITER_REGION_FRACTION and \
                   (max(cys) - min(cys)) < T.LOITER_REGION_FRACTION:
                    f0, f1 = min(tr.frames), max(tr.frames)
                    conf = float(np.mean(tr.confs))
                    db.add(TimelineEvent(
                        case_id=case.id, video_id=uuid.UUID(tr.video_id),
                        event_type="suspicious_flag", label="loitering",
                        start_ms=_ms(f0, fps), end_ms=_ms(f1, fps), start_frame=f0, end_frame=f1,
                        person_id=person.id,
                        description=f"Person {person.label} remains in the same small region "
                                    f"for {duration:.0f}s",
                        confidence=conf, is_suspicious=True,
                        requires_human_review=T.review_flag(conf),
                        evidence_frame_s3_keys=[f"{prefix_by_vid[tr.video_id]}{f0:06d}.jpg"],
                    ))
            # person_down: sustained lying_down posture > 5s
            down_run = 0
            for i in range(len(tr.frames)):
                x1, y1, x2, y2 = tr.boxes[i]
                down_run = down_run + 1 if (x2 - x1) > (y2 - y1) else 0
                if down_run / fps >= T.PERSON_DOWN_SECONDS:
                    f1 = tr.frames[i]
                    f0 = tr.frames[max(i - down_run + 1, 0)]
                    conf = float(np.mean(tr.confs))
                    db.add(TimelineEvent(
                        case_id=case.id, video_id=uuid.UUID(tr.video_id),
                        event_type="suspicious_flag", label="person_down",
                        start_ms=_ms(f0, fps), end_ms=_ms(f1, fps), start_frame=f0, end_frame=f1,
                        person_id=person.id,
                        description=f"Person {person.label} down for more than "
                                    f"{T.PERSON_DOWN_SECONDS}s",
                        confidence=conf, is_suspicious=True,
                        requires_human_review=T.review_flag(conf),
                        evidence_frame_s3_keys=[f"{prefix_by_vid[tr.video_id]}{f0:06d}.jpg"],
                    ))
                    break
    db.commit()


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

    if ref.face_embedding is None:
        models = _load_models()
        data = storage.get_bytes(ref.s3_key_photo)
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        faces = models["faces"].get(img) if img is not None else []
        if not faces:
            audit.log(db, action="suspect.match.computed", actor_type="system", case_id=case.id,
                      entity_type="suspect_reference", entity_id=ref.id,
                      detail={"error": "no_face_detected"})
            return
        best = max(faces, key=lambda f: f.det_score)
        ref.face_embedding = best.normed_embedding.astype(float).tolist()
        ref.face_detection_confidence = float(best.det_score)

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
            sim = _cos(ref.face_embedding, p.face_embedding)
            if sim >= T.SUSPECT_MATCH_COS:
                verdict = "match"
            elif sim >= T.SUSPECT_POSSIBLE_COS:
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
                  detail={"person_label": p.label, "cosine_similarity": round(sim, 4),
                          "verdict": verdict})


def _update_counts(db, case: Case) -> None:
    persons = db.execute(select(Person).where(Person.case_id == case.id)).scalars().all()
    case.person_count_total = len(persons)
    case.person_count_male = sum(1 for p in persons if p.gender_estimate == "male")
    case.person_count_female = sum(1 for p in persons if p.gender_estimate == "female")
    case.person_count_unknown_gender = sum(1 for p in persons if p.gender_estimate == "unknown")
    db.commit()
