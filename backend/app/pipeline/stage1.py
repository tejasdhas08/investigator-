"""Stage 1: ingestion & preprocessing (ARCHITECTURE.md Section 4, Stage 1).

Frame extraction, audio extraction, normalization, quality probing, shot boundaries.
Photos are converted into 1-frame "videos" so downstream stages need no special-casing.
Requires ffmpeg/ffprobe on the worker image.
"""
import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.case import Case
from app.models.timeline_event import TimelineEvent
from app.models.video import Video
from app.services import audit, progress, storage

ALLOWED_VIDEO_CODECS = {"h264", "hevc", "vp9", "mjpeg", "mpeg4"}


class ValidationFailure(Exception):
    pass


def run(case_id: str) -> None:
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        if case is None:
            raise ValidationFailure("case not found")
        case.status = "ingesting"
        db.commit()
        progress.set_progress(case_id, "ingesting", 0)

        videos = db.execute(
            select(Video).where(Video.case_id == case.id, Video.upload_complete)
        ).scalars().all()
        if not videos:
            raise ValidationFailure("no uploaded media")

        failures = []
        for i, video in enumerate(videos):
            try:
                _process_one(db, case, video)
            except ValidationFailure as exc:
                failures.append({"video_id": str(video.id), "reason": str(exc)})
            progress.set_progress(case_id, "ingesting", int((i + 1) / len(videos) * 100))
            db.commit()

        succeeded = len(videos) - len(failures)
        if succeeded == 0:
            raise ValidationFailure(json.dumps(failures))
        if failures:
            case.failure_reason = json.dumps({"partial_ingest_failures": failures})
        audit.log(db, action="pipeline.stage1.complete", actor_type="system", case_id=case.id,
                  detail={"videos": len(videos), "failed": len(failures)})
        case.status = "detecting"
        db.commit()


def _process_one(db, case, video: Video) -> None:
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="csai-stage1-"))
    try:
        local = workdir / f"original{pathlib.Path(video.s3_key_original).suffix}"
        storage.download_file(video.s3_key_original, str(local))
        if local.stat().st_size == 0:
            raise ValidationFailure("empty file")

        # Chain of custody: recomputed hash must match the client-supplied hash.
        sha = hashlib.sha256(local.read_bytes()).hexdigest()
        if sha != video.sha256:
            raise ValidationFailure("sha256 mismatch — upload corrupted or tampered")

        if video.media_type == "photo":
            _process_photo(video, local, workdir)
        else:
            _process_video(db, case, video, local, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _ffprobe(path: pathlib.Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise ValidationFailure(f"unreadable media: {out.stderr[:200]}")
    return json.loads(out.stdout)


def _run_ffmpeg(args: list[str], err: str) -> None:
    out = subprocess.run(["ffmpeg", "-y", "-err_detect", "ignore_err", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise ValidationFailure(f"{err}: {out.stderr[-300:]}")


def _process_photo(video: Video, local: pathlib.Path, workdir: pathlib.Path) -> None:
    frames_dir = workdir / "frames"
    frames_dir.mkdir()
    frame_path = frames_dir / "000000.jpg"
    _run_ffmpeg(["-i", str(local), "-q:v", "2", str(frame_path)], "photo conversion failed")
    probe = _ffprobe(frame_path)
    stream = probe["streams"][0]

    prefix = f"cases/{video.case_id}/media/{video.id}/frames/"
    storage.upload_file(str(frame_path), prefix + "000000.jpg")
    video.s3_prefix_frames = prefix
    video.width = int(stream["width"])
    video.height = int(stream["height"])
    video.fps_sampled = 1.0
    video.frame_count_sampled = 1
    video.quality_notes = []


def _sample_fps(duration_s: float, fps_original: float) -> float:
    if duration_s > 45 * 60:
        return 2.0
    if duration_s > 20 * 60:
        return 3.0
    return min(5.0, fps_original) if fps_original > 0 else 5.0


def _process_video(db, case, video: Video, local: pathlib.Path, workdir: pathlib.Path) -> None:
    from app.core.config import settings

    probe = _ffprobe(local)
    vstreams = [s for s in probe["streams"] if s["codec_type"] == "video"]
    astreams = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    if not vstreams:
        raise ValidationFailure("no video stream")
    vs = vstreams[0]
    codec = vs.get("codec_name", "")
    if codec not in ALLOWED_VIDEO_CODECS:
        raise ValidationFailure(f"unsupported codec: {codec}")
    duration = float(probe["format"].get("duration") or vs.get("duration") or 0)
    if duration > settings.max_video_seconds:
        raise ValidationFailure(f"video too long: {duration:.0f}s > {settings.max_video_seconds}s")
    num, _, den = (vs.get("avg_frame_rate") or "0/1").partition("/")
    fps_original = (float(num) / float(den)) if float(den or 1) else 0.0

    quality_notes: list[str] = []
    if "truncated" in (probe["format"].get("tags", {}).get("comment", "")):
        quality_notes.append("truncated_file")

    # Normalized 720p h264 copy for the browser player; original kept untouched.
    norm = workdir / "normalized.mp4"
    _run_ffmpeg(
        ["-i", str(local), "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264",
         "-preset", "fast", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", str(norm)],
        "normalization failed",
    )
    norm_key = f"cases/{video.case_id}/media/{video.id}/normalized.mp4"
    storage.upload_file(str(norm), norm_key)

    fps_sampled = _sample_fps(duration, fps_original)
    frames_dir = workdir / "frames"
    frames_dir.mkdir()
    _run_ffmpeg(
        ["-i", str(norm), "-vf", f"fps={fps_sampled}", "-q:v", "3",
         str(frames_dir / "%06d_tmp.jpg")],
        "frame extraction failed",
    )
    # ffmpeg numbers from 1; rename to 0-based to keep timestamp_ms = idx / fps * 1000.
    frames = sorted(frames_dir.glob("*_tmp.jpg"))
    prefix = f"cases/{video.case_id}/media/{video.id}/frames/"
    for idx, f in enumerate(frames):
        storage.upload_file(str(f), f"{prefix}{idx:06d}.jpg")

    audio_key = None
    if astreams:
        wav = workdir / "audio.wav"
        _run_ffmpeg(["-i", str(local), "-vn", "-ac", "1", "-ar", "16000", str(wav)], "audio extraction failed")
        audio_key = f"cases/{video.case_id}/media/{video.id}/audio.wav"
        storage.upload_file(str(wav), audio_key)

    quality_notes += _probe_quality(frames)
    norm_probe = _ffprobe(norm)
    nvs = [s for s in norm_probe["streams"] if s["codec_type"] == "video"][0]

    video.s3_key_normalized = norm_key
    video.s3_prefix_frames = prefix
    video.s3_key_audio = audio_key
    video.has_audio = bool(astreams)
    video.duration_seconds = duration
    video.fps_original = fps_original
    video.fps_sampled = fps_sampled
    video.frame_count_sampled = len(frames)
    video.width = int(nvs["width"])
    video.height = int(nvs["height"])
    video.quality_notes = quality_notes

    _detect_scene_changes(db, case, video, norm)


def _probe_quality(frames: list[pathlib.Path]) -> list[str]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []  # cv2 only on worker images; quality probing is best-effort
    from app.pipeline import thresholds as T

    notes = []
    lumas, blurs = [], []
    for f in frames:
        img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        lumas.append(float(np.mean(img)))
        blurs.append(float(cv2.Laplacian(img, cv2.CV_64F).var()))
    if lumas and sum(1 for v in lumas if v < T.LOW_LIGHT_LUMA) >= T.LOW_LIGHT_MIN_SECONDS:
        notes.append("low_light")
    if blurs and sum(1 for v in blurs if v < T.BLUR_LAPLACIAN_VAR) / len(blurs) > T.BLUR_FRAME_FRACTION:
        notes.append("motion_blur")
    return notes


def _detect_scene_changes(db, case, video: Video, norm: pathlib.Path) -> None:
    try:
        from scenedetect import ContentDetector, detect
    except ImportError:
        return  # scene detection is best-effort; tracking still resets per video
    from app.pipeline.thresholds import SCENE_CUT_THRESHOLD

    for scene_start, _ in detect(str(norm), ContentDetector(threshold=SCENE_CUT_THRESHOLD)):
        ms = int(scene_start.get_seconds() * 1000)
        if ms == 0:
            continue
        frame = int(ms / 1000 * (video.fps_sampled or 5.0))
        db.add(TimelineEvent(
            case_id=case.id, video_id=video.id, event_type="scene_change",
            start_ms=ms, end_ms=ms, start_frame=frame, end_frame=frame,
            label="cut_or_scene_change", confidence=0.95,
            evidence_frame_s3_keys=[f"{video.s3_prefix_frames}{frame:06d}.jpg"],
        ))
