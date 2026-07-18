"""The Timeline JSON contract (Section 3.10) is the load-bearing interface between
Stage 2 and Stage 3 — these tests pin its validation rules."""
import pytest
from pydantic import ValidationError

from app.schemas.timeline import CaseTimeline


def test_fixture_validates(fixture_timeline_dict):
    t = CaseTimeline.model_validate(fixture_timeline_dict)
    assert t.counts.persons_total == 3
    assert t.counts.unknown_gender == 1
    # fixture must exercise every branch Stage 3 handles (Phase 3 done-criteria)
    assert any(not p.face_visible for p in t.persons)
    assert any(e.event_type == "interaction" and e.actor_direction is None for e in t.events)
    assert any(e.object_class == "knife" and 0.40 <= e.confidence < 0.70 for e in t.events)
    assert any(e.label == "loitering" for e in t.events)


def test_unknown_person_label_rejected(fixture_timeline_dict):
    fixture_timeline_dict["events"][0]["person_label"] = "ZZ"
    with pytest.raises(ValidationError):
        CaseTimeline.model_validate(fixture_timeline_dict)


def test_interaction_requires_target(fixture_timeline_dict):
    for e in fixture_timeline_dict["events"]:
        if e["event_type"] == "interaction":
            e["target_person_label"] = None
    with pytest.raises(ValidationError):
        CaseTimeline.model_validate(fixture_timeline_dict)


def test_counts_must_sum(fixture_timeline_dict):
    fixture_timeline_dict["counts"]["male"] += 1
    with pytest.raises(ValidationError):
        CaseTimeline.model_validate(fixture_timeline_dict)


def test_start_after_end_rejected(fixture_timeline_dict):
    fixture_timeline_dict["events"][1]["end_ms"] = fixture_timeline_dict["events"][1]["start_ms"] - 1
    with pytest.raises(ValidationError):
        CaseTimeline.model_validate(fixture_timeline_dict)


def test_wrong_label_vocabulary_rejected(fixture_timeline_dict):
    fixture_timeline_dict["events"][1]["label"] = "teleporting"
    with pytest.raises(ValidationError):
        CaseTimeline.model_validate(fixture_timeline_dict)


def test_evidence_frames_required(fixture_timeline_dict):
    fixture_timeline_dict["events"][0]["evidence_frame_s3_keys"] = []
    with pytest.raises(ValidationError):
        CaseTimeline.model_validate(fixture_timeline_dict)
