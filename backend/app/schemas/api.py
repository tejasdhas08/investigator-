"""Request/response bodies for the REST API (ARCHITECTURE.md Section 5)."""
import uuid
from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, EmailStr, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ErrorBody(BaseModel):
    error: str
    message: str


# ---- auth ----
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    access_token: str
    expires_in: int
    user: UserOut


# ---- cases ----
class CaseCreate(BaseModel):
    case_number: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    context_description: str = Field(min_length=1, max_length=10000)


class CasePatch(BaseModel):
    title: str | None = None
    context_description: str | None = None


class VideoOut(BaseModel):
    id: uuid.UUID
    media_type: str
    original_filename: str
    duration_seconds: float | None
    width: int | None
    height: int | None
    has_audio: bool
    quality_notes: list | None
    upload_complete: bool
    stream_url: str | None = None
    model_config = {"from_attributes": True}


class CaseOut(BaseModel):
    id: uuid.UUID
    case_number: str
    title: str
    context_description: str
    status: str
    failure_reason: str | None
    owner_id: uuid.UUID
    narrative_json: dict | None
    narrative_generated_at: datetime | None
    person_count_total: int | None
    person_count_male: int | None
    person_count_female: int | None
    person_count_unknown_gender: int | None
    retention_expires_at: datetime
    created_at: datetime
    model_config = {"from_attributes": True}


class CaseListItem(BaseModel):
    id: uuid.UUID
    case_number: str
    title: str
    status: str
    person_count_total: int | None
    created_at: datetime
    model_config = {"from_attributes": True}


class CaseStatusOut(BaseModel):
    status: str
    stage: str | None = None
    stage_progress_pct: int | None = None
    failure_reason: str | None = None


# ---- media ----
class MediaUploadRequest(BaseModel):
    filename: str
    media_type: Literal["video", "photo"]
    content_type: str
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MediaUploadResponse(BaseModel):
    video_id: uuid.UUID
    upload_url: str
    s3_key: str


class MediaCompleteRequest(BaseModel):
    start_processing: bool = False


# ---- persons / timeline ----
class PersonOut(BaseModel):
    id: uuid.UUID
    label: str
    display_alias: str | None
    gender_estimate: str
    gender_confidence: float | None
    gender_human_override: str | None
    age_estimate_range: str | None
    face_visible: bool
    detection_confidence_avg: float
    appearance_description: str | None
    activity_summary: str | None
    first_seen_ms: int | None
    last_seen_ms: int | None
    presence_intervals: list | None
    is_suspect_match: bool
    face_crop_url: str | None = None
    body_crop_url: str | None = None
    model_config = {"from_attributes": True}


class TimelineEventOut(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID
    event_type: str
    start_ms: int
    end_ms: int
    start_frame: int
    end_frame: int
    person_id: uuid.UUID | None
    person_label: str | None = None
    target_person_id: uuid.UUID | None
    target_person_label: str | None = None
    label: str
    description: str | None
    confidence: float
    bbox: dict | None
    object_class: str | None
    actor_direction: str | None
    is_suspicious: bool
    requires_human_review: bool
    review_status: str
    human_note: str | None
    evidence_frame_urls: list[str] = []
    model_config = {"from_attributes": True}


class EventReviewRequest(BaseModel):
    action: Literal["approve", "reject", "edit"]
    human_note: str | None = None


class NarrativeEditRequest(BaseModel):
    path: str
    edited_text: str


class PersonOverrideRequest(BaseModel):
    gender_estimate: Literal["male", "female", "unknown"] | None = None
    display_alias: str | None = None


# ---- suspects ----
class SuspectCreateRequest(BaseModel):
    display_name: str
    filename: str
    content_type: str
    size_bytes: int = Field(gt=0)
    sha256: str


class SuspectCreateResponse(BaseModel):
    suspect_reference_id: uuid.UUID
    upload_url: str


class SuspectMatchResultOut(BaseModel):
    id: uuid.UUID
    person_id: uuid.UUID
    person_label: str | None = None
    cosine_similarity: float
    verdict: str
    best_frame_ms: int | None
    review_status: str
    comparison_face_url: str | None = None
    model_config = {"from_attributes": True}


class SuspectReferenceOut(BaseModel):
    id: uuid.UUID
    display_name: str
    photo_url: str | None = None
    results: list[SuspectMatchResultOut] = []


class MatchReviewRequest(BaseModel):
    action: Literal["confirm", "reject"]


# ---- chat ----
class ChatAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list | None
    model: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


# ---- exports ----
class ExportCreateRequest(BaseModel):
    includes_chat: bool = False


class ExportOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    generated_by: uuid.UUID
    sha256: str | None
    status: str
    includes_chat: bool
    model_config = {"from_attributes": True}
