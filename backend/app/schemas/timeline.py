"""Canonical Timeline JSON contract between Stage 2 (detection) and Stage 3 (narrative).

This mirrors ARCHITECTURE.md Section 3.10 exactly. Stage 2 (real or fake) MUST emit a
document validating against CaseTimeline; Stage 3 consumes only this.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

EventType = Literal[
    "person_appearance", "person_exit", "action", "interaction",
    "object_detection", "suspicious_flag", "scene_change",
]

ACTION_LABELS = {
    "standing", "walking", "running", "sitting", "lying_down", "crouching", "reaching",
    "carrying_object", "looking_around", "using_phone", "entering_vehicle",
    "exiting_vehicle", "opening_door", "climbing", "falling", "other",
}
INTERACTION_LABELS = {
    "physical_contact", "close_approach", "handover_object", "pursuit",
    "conversation_posture", "struggle", "other",
}
SUSPICIOUS_LABELS = {
    "loitering", "concealment_behavior", "forced_entry_indicators", "weapon_visible",
    "person_down", "rapid_group_dispersal", "other",
}
LABELS_BY_TYPE: dict[str, set[str]] = {
    "person_appearance": {"enters_frame"},
    "person_exit": {"exits_frame"},
    "action": ACTION_LABELS,
    "interaction": INTERACTION_LABELS,
    "object_detection": {"object_present"},
    "suspicious_flag": SUSPICIOUS_LABELS,
    "scene_change": {"cut_or_scene_change"},
}


class BBox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(ge=0, le=1)
    h: float = Field(ge=0, le=1)


class TimelineVideo(BaseModel):
    video_id: str
    media_type: Literal["video", "photo"]
    original_filename: str
    duration_ms: int | None = None
    fps_sampled: float
    width: int
    height: int
    has_audio: bool = False
    quality_notes: list[str] = []


class SuspectMatchInfo(BaseModel):
    suspect_reference_id: str
    display_name: str
    verdict: Literal["match", "possible_match", "no_match"]
    cosine_similarity: float


class PresenceInterval(BaseModel):
    video_id: str
    start_ms: int
    end_ms: int


class TimelinePerson(BaseModel):
    person_id: str
    label: str
    gender_estimate: Literal["male", "female", "unknown"]
    gender_confidence: float | None = None
    age_estimate_range: str | None = None
    appearance_description: str | None = None
    face_visible: bool
    detection_confidence_avg: float = Field(ge=0, le=1)
    first_seen_ms: int
    last_seen_ms: int
    presence_intervals: list[PresenceInterval]
    suspect_match: SuspectMatchInfo | None = None


class TimelineEventItem(BaseModel):
    event_id: str
    video_id: str
    event_type: EventType
    start_ms: int
    end_ms: int
    start_frame: int
    end_frame: int
    person_label: str | None = None
    target_person_label: str | None = None
    label: str
    description: str | None = None
    confidence: float = Field(ge=0, le=1)
    is_suspicious: bool = False
    requires_human_review: bool = False
    object_class: str | None = None
    actor_direction: str | None = None
    bbox: BBox | None = None
    evidence_frame_s3_keys: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _rules(self):
        if self.start_ms > self.end_ms:
            raise ValueError("start_ms must be <= end_ms")
        allowed = LABELS_BY_TYPE[self.event_type]
        if self.label not in allowed:
            raise ValueError(f"label '{self.label}' not allowed for event_type '{self.event_type}'")
        if self.label == "other" and not self.description:
            raise ValueError("description is mandatory when label='other'")
        if self.event_type == "interaction" and (not self.person_label or not self.target_person_label):
            raise ValueError("interaction events require person_label and target_person_label")
        if self.event_type == "object_detection" and not self.object_class:
            raise ValueError("object_detection events require object_class")
        return self


class TimelineCounts(BaseModel):
    persons_total: int
    male: int
    female: int
    unknown_gender: int


class CaseTimeline(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    generated_at: str
    videos: list[TimelineVideo]
    persons: list[TimelinePerson]
    events: list[TimelineEventItem]
    counts: TimelineCounts

    @model_validator(mode="after")
    def _cross_refs(self):
        labels = {p.label for p in self.persons}
        video_ids = {v.video_id for v in self.videos}
        for e in self.events:
            if e.person_label is not None and e.person_label not in labels:
                raise ValueError(f"event {e.event_id} references unknown person_label {e.person_label}")
            if e.target_person_label is not None and e.target_person_label not in labels:
                raise ValueError(f"event {e.event_id} references unknown target_person_label")
            if e.video_id not in video_ids:
                raise ValueError(f"event {e.event_id} references unknown video_id")
        c = self.counts
        if c.persons_total != len(self.persons):
            raise ValueError("counts.persons_total must equal len(persons)")
        if c.male + c.female + c.unknown_gender != c.persons_total:
            raise ValueError("gender counts must sum to persons_total")
        return self
