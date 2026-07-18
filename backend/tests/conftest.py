import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LLM_FAKE", "1")
os.environ.setdefault("PIPELINE_FAKE", "1")

import json
import pathlib
import uuid

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture_timeline() -> dict:
    """Builds a full CaseTimeline document from the hand-authored fixture."""
    raw = json.loads((FIXTURES / "timeline_fixture.json").read_text())
    video_id = str(uuid.uuid4())
    persons = []
    for p in raw["persons"]:
        persons.append({
            "person_id": str(uuid.uuid4()),
            "label": p["label"],
            "gender_estimate": p["gender_estimate"],
            "gender_confidence": p["gender_confidence"],
            "age_estimate_range": p["age_estimate_range"],
            "appearance_description": p["appearance_description"],
            "face_visible": p["face_visible"],
            "detection_confidence_avg": p["detection_confidence_avg"],
            "first_seen_ms": p["first_seen_ms"],
            "last_seen_ms": p["last_seen_ms"],
            "presence_intervals": [
                {"video_id": video_id, "start_ms": p["first_seen_ms"], "end_ms": p["last_seen_ms"]}
            ],
            "suspect_match": None,
        })
    events = []
    for e in raw["events"]:
        events.append({
            "event_id": str(uuid.uuid4()),
            "video_id": video_id,
            "event_type": e["event_type"],
            "start_ms": e["start_ms"],
            "end_ms": e["end_ms"],
            "start_frame": int(e["start_ms"] / 200),
            "end_frame": int(e["end_ms"] / 200),
            "person_label": e.get("person_label"),
            "target_person_label": e.get("target_person_label"),
            "label": e["label"],
            "description": e.get("description"),
            "confidence": e["confidence"],
            "is_suspicious": e.get("is_suspicious", False),
            "requires_human_review": e.get("requires_human_review", False),
            "object_class": e.get("object_class"),
            "actor_direction": e.get("actor_direction"),
            "bbox": e.get("bbox"),
            "evidence_frame_s3_keys": ["cases/x/frames/000000.jpg"],
        })
    male = sum(1 for p in persons if p["gender_estimate"] == "male")
    female = sum(1 for p in persons if p["gender_estimate"] == "female")
    return {
        "schema_version": "1.0",
        "case_id": str(uuid.uuid4()),
        "generated_at": "2026-07-18T00:00:00Z",
        "videos": [{
            "video_id": video_id, "media_type": "video", "original_filename": "cam1.mp4",
            "duration_ms": 184000, "fps_sampled": 5.0, "width": 1280, "height": 720,
            "has_audio": True, "quality_notes": ["low_light"],
        }],
        "persons": persons,
        "events": events,
        "counts": {
            "persons_total": len(persons), "male": male, "female": female,
            "unknown_gender": len(persons) - male - female,
        },
    }


@pytest.fixture
def fixture_timeline_dict():
    return load_fixture_timeline()


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.db import Base
    import app.models  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
