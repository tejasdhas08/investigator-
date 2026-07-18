# CrimeScene AI — Complete Architecture & Build Specification

**Document status:** Authoritative build specification. The implementing model must follow this document exactly and make no architectural decisions of its own. Anything not specified here is either (a) covered by the stated defaults in each section, or (b) listed in Section 9 as an open assumption.

**Product:** CrimeScene AI — an AI-powered investigation co-pilot for police, investigation bureaus, and forensic teams. It analyzes uploaded crime-scene/CCTV video or photos plus an investigator-provided context description, and produces a fully evidence-cited case summary: narrative story, detected people (anonymously labeled A/B/C…), person counts and gender breakdown, per-person activity descriptions, suspicious-activity flags, suspicious-object detections, suspect reference-photo matching, and an interactive Q&A chat. It is a decision-support tool that assists human investigators; it never replaces them and is never a sole source of legal truth. Every claim is timestamp-cited with a confidence score; every ambiguity is flagged, never guessed.

---

## 1. SYSTEM OVERVIEW

### 1.1 High-level component diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              INVESTIGATOR (browser)                          │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ HTTPS (JWT auth)
┌───────────────▼──────────────────────────────────────────────────────────────┐
│  FRONTEND SPA (React + TypeScript)                                           │
│  Screens: Login · Case List · New Case/Upload · Processing Status ·          │
│  Case Dashboard (Narrative / People / Timeline / Suspicious Activity /       │
│  Objects / Suspect Match / Chat Q&A / Review & Export)                       │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ REST + polling (JSON)
┌───────────────▼──────────────────────────────────────────────────────────────┐
│  API GATEWAY / BACKEND (FastAPI, Python 3.12)                                │
│  - Auth service (JWT, RBAC)                                                  │
│  - Case service (CRUD, status)                                               │
│  - Upload service (pre-signed S3 URLs, media validation)                     │
│  - Chat/Q&A service (context assembly → LLM)                                 │
│  - Report/export service (PDF generation)                                    │
│  - Audit log service (append-only writes on every mutation & AI claim)       │
└─────┬───────────────────────┬───────────────────────────┬────────────────────┘
      │ enqueue jobs          │ read/write                │ read/write
┌─────▼─────────┐   ┌─────────▼─────────┐   ┌─────────────▼────────────────────┐
│ REDIS         │   │ POSTGRESQL 16     │   │ OBJECT STORAGE (S3 / MinIO)      │
│ (Celery broker│   │ cases, users,     │   │ raw video/photos, extracted      │
│  + status     │   │ persons, events,  │   │ frames, face crops, person       │
│  cache)       │   │ chats, audits,    │   │ thumbnails, reference photos,    │
└─────┬─────────┘   │ matches, exports  │   │ exported PDF reports             │
      │             └───────────────────┘   └──────────────────────────────────┘
      │ consume
┌─────▼────────────────────────────────────────────────────────────────────────┐
│  WORKER FLEET (Celery workers; GPU node for Stage 2)                         │
│  Stage 1: Ingestion & Preprocessing (ffmpeg: frames, audio, normalize)       │
│  Stage 2: Detection & Tracking (YOLOv8 + ByteTrack + InsightFace:            │
│           faces, person tracks, gender, objects/weapons, suspect matching)   │
│  Stage 3: Narrative Engine (timeline JSON → Claude API → cited story)        │
│  (Stage 4 Q&A and Stage 5 Review/Export run in the API layer, on demand)     │
└─────┬────────────────────────────────────────────────────────────────────────┘
      │ HTTPS
┌─────▼─────────────────────┐
│  ANTHROPIC CLAUDE API     │  (narrative generation + Q&A answers)
└───────────────────────────┘
```

### 1.2 Data flow (happy path)

1. Investigator logs in → creates a Case → uploads video/photos via pre-signed S3 URLs → submits context description → API enqueues `process_case` job.
2. Worker Stage 1 pulls media from S3, extracts/normalizes frames + audio, writes frames to S3, records `Video` metadata in Postgres.
3. Worker Stage 2 runs detection/tracking over frames, producing: `Person` rows (with face crops in S3 and nicknames A, B, C…), `TimelineEvent` rows, object detections, suspicious-activity flags, and (if a reference photo exists) `SuspectMatchResult` rows.
4. Worker Stage 3 assembles the canonical **Timeline JSON** (Section 3.10), calls the Claude API with the fixed system prompt (Section 4, Stage 3), validates the returned cited narrative, and stores it on the Case.
5. Frontend polls status; on `complete` it renders the Case Dashboard from Postgres + S3 URLs.
6. Investigator asks follow-up questions (Stage 4): API assembles case context + timeline + chat history → Claude API → cited answer stored as `ChatMessage`.
7. Investigator reviews, edits/approves/rejects claims (Stage 5), then exports a PDF report; all edits and every AI claim are audit-logged.

### 1.3 Pipeline stages/services mapped to product features

| Stage / service | Owns | Fulfills product feature(s) |
|---|---|---|
| Upload service + Stage 1 (Ingestion) | Media validation, frame/audio extraction, normalization, photo-as-single-frame handling | "Investigator uploads a video or photos"; "provides a short text description" (stored on Case) |
| Stage 2 (Detection & Tracking) | Face detection, person tracking & re-ID, gender estimation, action labeling, object/weapon detection, suspect matching | "Detection of every person"; "anonymous nickname A/B/C"; "exact total count"; "gender breakdown"; "what each person was doing"; "suspicious objects/materials"; "suspect matching" |
| Stage 3 (Narrative Engine) | Timeline JSON assembly, LLM narrative with citations, suspicious-activity synthesis, interaction claims with evidence gating | "Clear, exact narrative story" (most important feature); "who attacked whom, when the footage supports it, and explicitly say when it does NOT"; "suspicious activity flagging"; "high intelligence analytical partner" |
| Stage 4 (Q&A service) | Context assembly, chat history, context-length management | "Interactive Q&A with contextual answers" |
| Stage 5 (Review & Export service) | Claim approval/rejection/editing, PDF report, AI-vs-human provenance | "All outputs reviewable, editable, verifiable by a human"; "decision-support, not replacement" |
| Audit log service | Append-only log of every AI claim, edit, view, export, deletion | "Traceability, audit logging designed in from the start" |
| Auth service | Investigator accounts, roles, sessions | Multi-user investigation teams; access control for sensitive footage |
| Retention scheduler (cron job) | Enforcing per-case retention policy, secure deletion | "Privacy, data retention designed in from the start" |

---

## 2. TECH STACK DECISIONS

These are decisions, not options. Build exactly this.

| Concern | Decision | Justification |
|---|---|---|
| Backend language/framework | **Python 3.12 + FastAPI** (Pydantic v2 for all schemas, SQLAlchemy 2.0 + Alembic for DB) | Python is the only sane host for the CV/ML stack (OpenCV, ultralytics, insightface, ffmpeg bindings). FastAPI gives async endpoints, automatic OpenAPI docs, and Pydantic validation matching the JSON schemas in Section 3. |
| Frontend | **React 18 + TypeScript + Vite**, Tailwind CSS, TanStack Query for server state, React Router v6 | Mature ecosystem, easy video-player and timeline components, TanStack Query handles the polling pattern cleanly. No SSR needed (internal tool behind login) — plain SPA. |
| Database | **PostgreSQL 16** (SQL) | Data is strongly relational (Case→Videos→Persons→Events; Chat→Case; Audit→everything) and legally sensitive — we need ACID, foreign keys, and immutable append-only audit tables. Semi-structured payloads (timeline JSON, LLM raw responses, bounding boxes) go in `JSONB` columns, giving NoSQL flexibility where needed without giving up integrity. Face embeddings stored via the **pgvector** extension (`vector(512)`) so suspect matching is a SQL query — no separate vector DB. NoSQL is rejected: no schema enforcement for evidence data is unacceptable in a legal-context tool. |
| File/video storage | **S3-compatible object storage**: AWS S3 in cloud deployment, **MinIO** in on-prem/air-gapped deployment (identical API, so one code path via `boto3`). Server-side encryption (SSE-S3/AES-256) mandatory. All frontend media access via time-limited (15-min) pre-signed URLs — the API never proxies video bytes. | Footage is large; DB storage is wrong. S3 API is the de-facto standard and MinIO keeps the on-prem requirement (police often cannot use public cloud) with zero code change. |
| Task queue / async | **Celery 5 + Redis 7** (Redis as broker and as processing-status cache). One default queue `cpu` and one `gpu` queue for Stage 2. Job chain: `stage1_ingest.s() | stage2_detect.s() | stage3_narrative.s()`. Frontend **polls** `GET /cases/{id}/status` every 3 s (no WebSockets in v1 — simpler, proxy-friendly). Workers write progress (stage name + percent) to Redis key `case:{id}:progress` with 24 h TTL. | Video processing takes minutes; it must never block an HTTP request. Celery chains give per-stage retry and failure isolation. Polling chosen over WebSockets as an explicit simplicity decision. |
| LLM | **Anthropic Claude API**. Narrative generation (Stage 3) and Q&A (Stage 4): model id `claude-fable-5`. Cheap utility calls (chat-history summarization in Stage 4): `claude-haiku-4-5-20251001`. Temperature 0.2 for narrative, 0.3 for Q&A. `max_tokens`: 8000 narrative, 2000 Q&A. | The narrative engine's core requirement is disciplined reasoning over structured evidence with strict refusal-to-overclaim; use the most capable available model for the legally sensitive output. |
| CV models | See Stage 2 spec (Section 4): YOLOv8m (ultralytics) for person+object detection, ByteTrack for tracking, InsightFace `buffalo_l` pack (SCRFD face detection + ArcFace embeddings + gender/age head). | Chosen in Section 4 with thresholds; listed here for completeness. |
| Hosting/deployment | **Docker Compose** for dev and single-node on-prem; images: `api`, `worker-cpu`, `worker-gpu`, `frontend` (nginx serving static build + reverse proxy to api), `postgres`, `redis`, `minio`. Production cloud target: the same images on a single GPU VM (e.g., AWS g5.xlarge) — **no Kubernetes in v1** (explicit decision). TLS terminated at nginx. Secrets via environment variables loaded from a `.env` file (dev) or the host's secret store (prod); never committed. | Police deployments are frequently on-prem; Compose is the lowest-friction path that still matches cloud. K8s deferred to a later phase deliberately. |
| PDF export | **WeasyPrint** (HTML → PDF) rendered server-side from a Jinja2 template. | Pure-Python, no headless browser dependency, deterministic output. |

Repository layout (monorepo):

```
/backend
  /app
    /api            # FastAPI routers (one file per resource)
    /core           # config, security, deps
    /models         # SQLAlchemy models
    /schemas        # Pydantic schemas (mirror Section 3 exactly)
    /services       # business logic (case, chat, export, audit)
    /pipeline       # Celery tasks: stage1.py stage2.py stage3.py
    /prompts        # prompt template files (narrative.txt, qa.txt)
  /alembic          # migrations
  /tests
/frontend
  /src
    /pages          # one file per screen in Section 6
    /components
    /api            # typed client matching Section 5
/deploy
  docker-compose.yml
  docker-compose.gpu.yml
/docs
  ARCHITECTURE.md   # this file
```

---

## 3. DATA MODELS

Conventions: primary keys are `id UUID DEFAULT gen_random_uuid()`. All timestamps are `TIMESTAMPTZ` in UTC named `created_at` / `updated_at`. All confidence scores are `REAL` in [0.0, 1.0]. Foreign keys are `ON DELETE CASCADE` unless stated (audit_log is `ON DELETE SET NULL` on FKs and rows are never deleted). All enums implemented as Postgres `TEXT` + `CHECK` constraints (not native enums, to ease migration).

### 3.1 `users` (User / Investigator)

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| email | TEXT UNIQUE NOT NULL | login identifier |
| full_name | TEXT NOT NULL | |
| badge_number | TEXT NULL | department identifier |
| department | TEXT NULL | |
| password_hash | TEXT NOT NULL | argon2id |
| role | TEXT NOT NULL CHECK IN ('investigator','supervisor','admin') | RBAC: investigator = own/assigned cases; supervisor = all cases read + approve exports; admin = user management + retention config. |
| is_active | BOOLEAN DEFAULT true | |
| mfa_totp_secret | TEXT NULL | encrypted at rest with `APP_ENCRYPTION_KEY` (AES-GCM); MFA mandatory for role != investigator, optional otherwise |
| created_at / updated_at | TIMESTAMPTZ | |
| last_login_at | TIMESTAMPTZ NULL | |

### 3.2 `cases` (Case)

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| case_number | TEXT UNIQUE NOT NULL | human case ref, user-supplied |
| title | TEXT NOT NULL | |
| context_description | TEXT NOT NULL | investigator's "what I believe happened" text; passed to Stage 3 as *hypothesis*, never as evidence |
| status | TEXT CHECK IN ('created','uploading','queued','ingesting','detecting','narrating','complete','failed','archived') | drives UI status screen |
| failure_reason | TEXT NULL | populated when status='failed' |
| owner_id | UUID FK → users.id | creating investigator |
| narrative_json | JSONB NULL | Stage 3 output, schema in 3.11 |
| narrative_model | TEXT NULL | exact model id used |
| narrative_generated_at | TIMESTAMPTZ NULL | |
| person_count_total | INT NULL | denormalized from persons for list views |
| person_count_male / person_count_female / person_count_unknown_gender | INT NULL | gender breakdown incl. below-threshold "unknown" bucket |
| retention_expires_at | TIMESTAMPTZ NOT NULL | created_at + retention policy (default 365 days; configurable per deployment) |
| created_at / updated_at | TIMESTAMPTZ | |

`case_members(case_id, user_id, role_in_case CHECK IN ('owner','collaborator','viewer'))` — join table for team access.

### 3.3 `videos` (Video / uploaded media)

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| case_id | UUID FK → cases.id | |
| media_type | TEXT CHECK IN ('video','photo') | photos flow through the same pipeline as 1-frame videos |
| original_filename | TEXT NOT NULL | |
| s3_key_original | TEXT NOT NULL | `cases/{case_id}/media/{video_id}/original.{ext}` |
| s3_key_normalized | TEXT NULL | Stage 1 output mp4 |
| s3_prefix_frames | TEXT NULL | `cases/{case_id}/media/{video_id}/frames/` |
| s3_key_audio | TEXT NULL | extracted wav, NULL if no audio track |
| sha256 | TEXT NOT NULL | integrity/chain-of-custody hash of original upload |
| duration_seconds | REAL NULL | NULL for photos |
| fps_original | REAL NULL | |
| fps_sampled | REAL NULL | analysis sampling rate chosen by Stage 1 |
| width / height | INT | after normalization |
| frame_count_sampled | INT NULL | |
| upload_complete | BOOLEAN DEFAULT false | |
| created_at | TIMESTAMPTZ | |

### 3.4 `persons` (detected + tracked person)

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| case_id | UUID FK → cases.id | person identity is **case-scoped and video-spanning**: Stage 2 merges tracks across all videos in the case via face embeddings |
| label | TEXT NOT NULL | anonymous nickname: 'A','B',…,'Z','AA','AB',… assigned in order of first appearance across the case |
| track_ids | JSONB NOT NULL | array of `{video_id, tracker_track_id}` raw ByteTrack ids merged into this person |
| first_seen_ms / last_seen_ms | BIGINT | across the case timeline |
| first_seen_video_id | UUID FK → videos.id | |
| face_embedding | vector(512) NULL | best-quality ArcFace embedding; NULL if face never visible |
| face_crop_s3_key | TEXT NULL | best face crop `cases/{case_id}/persons/{person_id}/face.jpg`; NULL → UI shows silhouette placeholder with note "face not visible in footage" |
| body_crop_s3_key | TEXT NOT NULL | best full-body crop (always available for a tracked person) |
| gender_estimate | TEXT CHECK IN ('male','female','unknown') | 'unknown' when confidence < threshold (Section 4 Stage 2) |
| gender_confidence | REAL NULL | |
| age_estimate_range | TEXT NULL | e.g. '25-35'; informational only, never in narrative as fact |
| detection_confidence_avg | REAL NOT NULL | mean person-detection confidence across track |
| activity_summary | TEXT NULL | Stage 3-generated one-paragraph "what this person did", with citations |
| appearance_description | TEXT NULL | Stage 2 CLIP/manual attribute string, e.g. "dark jacket, backpack" (see Stage 2 step 7) |
| is_suspect_match | BOOLEAN DEFAULT false | denormalized: any accepted match result |
| created_at | TIMESTAMPTZ | |

UNIQUE(case_id, label).

### 3.5 `timeline_events` (Timeline Event)

One row per atomic observation emitted by Stage 2. This table is the DB materialization of the Timeline JSON (3.10).

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| case_id | UUID FK | |
| video_id | UUID FK → videos.id | |
| event_type | TEXT CHECK IN ('person_appearance','person_exit','action','interaction','object_detection','suspicious_flag','scene_change') | |
| start_ms / end_ms | BIGINT NOT NULL | video-relative milliseconds; equal for instantaneous events |
| start_frame / end_frame | INT NOT NULL | sampled-frame indices |
| person_id | UUID FK → persons.id NULL | primary subject |
| target_person_id | UUID FK → persons.id NULL | for `interaction`: the acted-upon person |
| label | TEXT NOT NULL | controlled vocabulary, see 3.10 |
| description | TEXT NULL | short machine-generated detail |
| confidence | REAL NOT NULL | |
| bbox | JSONB NULL | `{x,y,w,h}` normalized 0–1, at start_frame |
| object_class | TEXT NULL | for object_detection: COCO/weapon class name |
| is_suspicious | BOOLEAN DEFAULT false | |
| requires_human_review | BOOLEAN DEFAULT false | set when confidence in [review band] or interaction is ambiguous |
| review_status | TEXT CHECK IN ('unreviewed','approved','rejected','edited') DEFAULT 'unreviewed' | Stage 5 |
| reviewed_by | UUID FK → users.id NULL | |
| human_note | TEXT NULL | Stage 5 edit/annotation |
| evidence_frame_s3_keys | JSONB NOT NULL | 1–3 representative frame image keys for UI evidence display |
| created_at | TIMESTAMPTZ | |

Index: `(case_id, start_ms)`, `(case_id, person_id)`, `(case_id, is_suspicious)`.

### 3.6 `chat_messages` (Chat Message)

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| case_id | UUID FK | |
| user_id | UUID FK → users.id NULL | NULL for assistant messages |
| role | TEXT CHECK IN ('user','assistant') | |
| content | TEXT NOT NULL | assistant content is markdown with inline citations `[t=MM:SS, conf 0.82]` |
| citations | JSONB NULL | array of `{event_id, start_ms, end_ms, confidence}` extracted from the answer |
| model | TEXT NULL | model id for assistant messages |
| token_count | INT NULL | |
| created_at | TIMESTAMPTZ | |

`chat_summaries(id, case_id, up_to_message_id, summary TEXT, created_at)` — rolling summaries for Stage 4 context management.

### 3.7 `suspect_references` + `suspect_match_results`

`suspect_references`:

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| case_id | UUID FK | |
| uploaded_by | UUID FK → users.id | |
| display_name | TEXT NOT NULL | investigator-supplied label, e.g. "Suspect from robbery #4411" — never treated as identity ground truth |
| s3_key_photo | TEXT NOT NULL | |
| face_embedding | vector(512) NOT NULL | reject upload with 422 if no face detectable in photo |
| face_detection_confidence | REAL NOT NULL | |
| created_at | TIMESTAMPTZ | |

`suspect_match_results`:

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| suspect_reference_id | UUID FK | |
| person_id | UUID FK → persons.id | candidate person in footage |
| cosine_similarity | REAL NOT NULL | |
| verdict | TEXT CHECK IN ('match','possible_match','no_match') | thresholds in Section 4 Stage 2 step 8 |
| best_frame_ms | BIGINT | timestamp of highest-similarity comparison |
| comparison_face_s3_key | TEXT | side-by-side crop used |
| review_status | TEXT CHECK IN ('unreviewed','confirmed','rejected') DEFAULT 'unreviewed' | a "match" is never final until a human confirms |
| reviewed_by | UUID FK → users.id NULL | |
| created_at | TIMESTAMPTZ | |

One row per (reference, person) pair — including `no_match` rows for the audit trail.

### 3.8 `export_reports` (Export Report)

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| case_id | UUID FK | |
| generated_by | UUID FK → users.id | |
| s3_key_pdf | TEXT NOT NULL | |
| sha256 | TEXT NOT NULL | report integrity hash, printed inside the PDF footer |
| includes_chat | BOOLEAN | export option |
| snapshot | JSONB NOT NULL | frozen copy of narrative + events + review statuses at export time (reports must not change retroactively) |
| created_at | TIMESTAMPTZ | |

### 3.9 `audit_log` (append-only; INSERT-only DB role; no UPDATE/DELETE grants)

| Field | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | monotonic |
| occurred_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| actor_type | TEXT CHECK IN ('user','system','ai') | |
| actor_user_id | UUID NULL | |
| case_id | UUID NULL | |
| action | TEXT NOT NULL | controlled vocabulary: `case.create`, `media.upload`, `media.view`, `pipeline.stage1.complete`, `pipeline.stage2.complete`, `ai.claim.created`, `ai.narrative.generated`, `ai.chat.answer`, `claim.approved`, `claim.rejected`, `claim.edited`, `suspect.match.computed`, `suspect.match.confirmed`, `export.generated`, `export.downloaded`, `case.deleted`, `retention.purge`, `auth.login`, `auth.login_failed` |
| entity_type / entity_id | TEXT / UUID NULL | what was acted on |
| detail | JSONB NOT NULL | action-specific payload; for `ai.claim.created` see Section 7.4 required fields |
| ip_address | INET NULL | |
| prev_row_sha256 | TEXT NOT NULL | hash chain: sha256(previous row's canonical JSON ‖ this row's detail) → tamper-evident log |

### 3.10 Timeline JSON — the contract between Stage 2 (detection) and Stage 3 (narrative)

This is the **exact** JSON document Stage 2 writes to S3 (`cases/{case_id}/timeline.json`) and Stage 3 consumes. Pydantic model name: `CaseTimeline`.

```json
{
  "schema_version": "1.0",
  "case_id": "uuid",
  "generated_at": "2026-07-18T12:00:00Z",
  "videos": [
    {
      "video_id": "uuid",
      "media_type": "video",
      "original_filename": "cam1.mp4",
      "duration_ms": 184000,
      "fps_sampled": 5.0,
      "width": 1280,
      "height": 720,
      "has_audio": true,
      "quality_notes": ["low_light_after_ms_120000", "motion_blur"]
    }
  ],
  "persons": [
    {
      "person_id": "uuid",
      "label": "A",
      "gender_estimate": "male",
      "gender_confidence": 0.91,
      "age_estimate_range": "25-35",
      "appearance_description": "dark hooded jacket, jeans, backpack",
      "face_visible": true,
      "detection_confidence_avg": 0.87,
      "first_seen_ms": 3200,
      "last_seen_ms": 171000,
      "presence_intervals": [
        {"video_id": "uuid", "start_ms": 3200, "end_ms": 92000},
        {"video_id": "uuid", "start_ms": 140000, "end_ms": 171000}
      ],
      "suspect_match": {
        "suspect_reference_id": "uuid",
        "display_name": "Suspect from robbery #4411",
        "verdict": "possible_match",
        "cosine_similarity": 0.58
      }
    }
  ],
  "events": [
    {
      "event_id": "uuid",
      "video_id": "uuid",
      "event_type": "action",
      "start_ms": 45200, "end_ms": 51000,
      "start_frame": 226, "end_frame": 255,
      "person_label": "A",
      "target_person_label": null,
      "label": "running",
      "description": "Person A runs toward the doorway on the right",
      "confidence": 0.78,
      "is_suspicious": false,
      "requires_human_review": false,
      "object_class": null,
      "bbox": {"x": 0.41, "y": 0.22, "w": 0.09, "h": 0.31},
      "evidence_frame_s3_keys": ["cases/.../frames/000230.jpg"]
    },
    {
      "event_id": "uuid",
      "video_id": "uuid",
      "event_type": "interaction",
      "start_ms": 51200, "end_ms": 54900,
      "start_frame": 256, "end_frame": 274,
      "person_label": "A",
      "target_person_label": "B",
      "label": "physical_contact",
      "description": "Person A makes rapid arm contact with Person B; B falls",
      "confidence": 0.64,
      "is_suspicious": true,
      "requires_human_review": true,
      "object_class": null,
      "bbox": {"x": 0.44, "y": 0.25, "w": 0.18, "h": 0.33},
      "evidence_frame_s3_keys": ["cases/.../frames/000258.jpg", "cases/.../frames/000265.jpg"]
    },
    {
      "event_id": "uuid",
      "video_id": "uuid",
      "event_type": "object_detection",
      "start_ms": 50800, "end_ms": 55400,
      "start_frame": 254, "end_frame": 277,
      "person_label": "A",
      "target_person_label": null,
      "label": "object_present",
      "description": "Elongated dark object in Person A's right hand",
      "confidence": 0.47,
      "is_suspicious": true,
      "requires_human_review": true,
      "object_class": "knife",
      "bbox": {"x": 0.49, "y": 0.31, "w": 0.03, "h": 0.06},
      "evidence_frame_s3_keys": ["cases/.../frames/000257.jpg"]
    }
  ],
  "counts": {
    "persons_total": 4,
    "male": 2,
    "female": 1,
    "unknown_gender": 1
  }
}
```

Controlled vocabulary for `label` by `event_type`:
- `person_appearance` / `person_exit`: `enters_frame`, `exits_frame`.
- `action`: `standing`, `walking`, `running`, `sitting`, `lying_down`, `crouching`, `reaching`, `carrying_object`, `looking_around`, `using_phone`, `entering_vehicle`, `exiting_vehicle`, `opening_door`, `climbing`, `falling`, `other` (with `description` mandatory for `other`).
- `interaction`: `physical_contact`, `close_approach`, `handover_object`, `pursuit`, `conversation_posture`, `struggle`, `other`.
- `object_detection`: always `object_present`, with `object_class` set.
- `suspicious_flag`: `loitering`, `concealment_behavior`, `forced_entry_indicators`, `weapon_visible`, `person_down`, `rapid_group_dispersal`, `other`.
- `scene_change`: `cut_or_scene_change` (from shot-boundary detection, so Stage 3 knows continuity breaks).

Rules the implementing model must enforce with Pydantic validation: every event's `person_label` must exist in `persons` (or be null for scene-level events); `start_ms <= end_ms`; `confidence` in [0,1]; every event has ≥1 `evidence_frame_s3_keys`; `interaction` events must have both `person_label` and `target_person_label`.

### 3.11 Narrative JSON (`cases.narrative_json`) — Stage 3 output schema

```json
{
  "schema_version": "1.0",
  "model": "claude-fable-5",
  "generated_at": "...",
  "overall_summary": "2-4 sentence abstract of the incident.",
  "narrative_sections": [
    {
      "section_index": 0,
      "time_range_ms": [0, 45000],
      "heading": "Arrival and initial movements",
      "text": "Person A enters from the left at 00:03 [e:uuid1, conf 0.87] and walks toward ...",
      "cited_event_ids": ["uuid1", "uuid2"]
    }
  ],
  "person_summaries": [
    {"person_label": "A", "text": "Person A is present from 00:03 to 02:51 ... [e:..., conf ...]", "cited_event_ids": ["..."]}
  ],
  "suspicious_activity_summary": [
    {"text": "...", "severity": "high", "cited_event_ids": ["..."], "requires_human_review": true}
  ],
  "uncertainties": [
    {"text": "It cannot be determined from the footage whether the contact at 00:51 was a deliberate strike or a collision; frames 256-274 are motion-blurred.", "related_event_ids": ["..."]}
  ],
  "evidence_gaps": ["No footage covers 01:32-02:20 (Person A off-camera)."],
  "disclaimer": "<exact text from Section 7.5>"
}
```

Citation token format inside all narrative/answer text: `[e:<event_id short8>, conf <0.xx>]` immediately after the claim it supports. The frontend parses these tokens into clickable chips that seek the video player.

### 3.12 Entity-relationship summary

```
users 1─N cases (owner) ; users N─M cases via case_members
cases 1─N videos ; cases 1─N persons ; cases 1─N timeline_events
cases 1─N chat_messages ; cases 1─N suspect_references ; cases 1─N export_reports
persons 1─N timeline_events (person_id, target_person_id)
suspect_references 1─N suspect_match_results N─1 persons
audit_log → soft references to everything (nullable FKs, never cascaded)
```

---

## 4. STAGE-BY-STAGE PIPELINE SPEC

### Stage 1 — Ingestion & Preprocessing

**Input:** `case_id`; list of uploaded media objects in S3 (`videos` rows with `upload_complete=true`).
**Output:** normalized mp4 (video) in S3, JPEG frame set in S3, wav audio in S3 (if present), fully populated `videos` row; case status → `detecting` handoff.

**Processing steps (exact):**
1. Set case status `ingesting`. Download original from S3 to worker local scratch.
2. Validate: allowed containers/codecs via `ffprobe` — accept mp4/mov/avi/mkv/webm video (h264/h265/vp9/mjpeg) and jpg/png/heic photos. Max upload size 4 GB per file, max duration 60 min per video, max 20 media files per case. Violations → status `failed` with `failure_reason` = specific message (e.g. `"unsupported codec: wmv2"`).
3. Verify stored `sha256` matches recomputed hash (chain of custody); mismatch → fail.
4. **Photos:** convert to JPEG (quality 90), treat as a 1-frame video: `duration_seconds=NULL`, `frame_count_sampled=1`, frame written as `frames/000000.jpg`. All later stages operate on frames, so photos need no special-casing downstream (tracking degenerates to single-frame detection; all `start_ms=end_ms=0`).
5. **Videos:** normalize with ffmpeg: transcode to h264 mp4, cap resolution at 1280×720 (preserve aspect; never upscale), strip nothing else; store as `s3_key_normalized`. This normalized copy is what the frontend player streams (original retained untouched for evidence integrity).
6. Frame sampling: extract JPEG frames at `fps_sampled = min(5.0, fps_original)`; if duration > 20 min, drop to 3.0 fps; if > 45 min, 2.0 fps (bounds worst-case frame count ≈ 9000). Name frames `%06d.jpg` by sampled index. Record `fps_sampled`, `frame_count_sampled`. Mapping rule used everywhere: `timestamp_ms = round(frame_index / fps_sampled * 1000)`.
7. Audio: if an audio stream exists, extract to 16 kHz mono wav. **v1 decision: audio is stored for human review/playback only — no ML audio analysis** (gunshot/scream detection is a listed future risk, Section 9). `has_audio` recorded.
8. Quality probing: compute mean luma per frame (flag `low_light_*` intervals when mean < 40/255 for >5 s) and Laplacian variance (flag `motion_blur` when < 50 on >30% of frames). Write to `videos` → later into `quality_notes` in Timeline JSON so Stage 3 can cite footage-quality caveats.
9. Shot-boundary detection with PySceneDetect (`ContentDetector`, threshold 27.0) → emit `scene_change` timeline events, so Stage 2 tracking resets at cuts and Stage 3 knows continuity breaks.
10. Upload artifacts to S3, delete local scratch, write `pipeline.stage1.complete` audit row, advance chain to Stage 2.

**Error handling:** Celery `autoretry_for=(IOError, botocore exceptions)`, `max_retries=3`, exponential backoff 10/30/90 s. Non-retryable validation failures set case `failed` immediately. A partially failed multi-file case: process remaining files, record per-file failure in `failure_reason` as JSON list, continue pipeline if ≥1 file succeeded.

**Edge cases:** zero-byte upload (fail, message "empty file"); video with no video stream (fail); corrupt tail (ffmpeg `-err_detect ignore_err`, process what decodes, add `quality_notes: ["truncated_file"]`); HDR/rotated metadata (apply `-vf transpose` per rotation tag); duplicate uploads (same sha256 within case → reject with 409 at upload-complete endpoint).

### Stage 2 — Detection, Tracking, Attributes, Objects, Suspect Matching

**Input:** frames in S3 + `videos` rows.
**Output:** `persons`, `timeline_events`, `suspect_match_results` rows; face/body crops in S3; canonical Timeline JSON written to S3.

**Models (exact choices and why):**

| Task | Model / library | Why |
|---|---|---|
| Person + object detection | **YOLOv8m** (ultralytics, COCO weights) | best accuracy/speed tradeoff on a single GPU; detects `person` plus COCO objects (knife, backpack, handbag, bottle, cell phone, baseball bat, scissors, car, truck) |
| Weapon-specific detection | **YOLOv8m fine-tuned on an open weapons dataset** (pistol/rifle/knife classes; e.g., the Soria "weapons and similar objects" dataset). Ship as second model file `weapons_yolov8m.pt`. | COCO alone misses firearms; dedicated head needed for the weapons feature |
| Multi-object tracking | **ByteTrack** (as integrated in ultralytics `model.track(tracker="bytetrack.yaml")`) | robust to occlusion via low-confidence box recovery — critical on CCTV |
| Face detection + alignment | **InsightFace SCRFD** (`buffalo_l` pack) | SOTA small-face detection for CCTV distances |
| Face embedding (re-ID + suspect match) | **InsightFace ArcFace** 512-d (`buffalo_l`) | standard, well-calibrated cosine behavior |
| Gender + age | **InsightFace genderage head** (`buffalo_l`) | comes with the pack; adequate; bias limits handled by thresholds + Section 7 |
| Appearance description | **OpenCLIP ViT-B/32** zero-shot over a fixed attribute prompt list (clothing colors/types, carried items) | cheap, deterministic vocabulary, no extra training |
| Action labels | Heuristic layer over tracks (speed/posture rules) **plus** per-track keyframe classification with OpenCLIP zero-shot over the controlled action vocabulary (3.10) | v1 decision: no heavyweight video-action model (SlowFast etc.) — CLIP-over-keyframes + kinematics covers the controlled vocabulary; listed as a risk (Section 9) |

**Exact thresholds (constants module `pipeline/thresholds.py` — single source of truth):**

| Constant | Value | Meaning |
|---|---|---|
| PERSON_DET_CONF | 0.45 | min YOLO confidence to consider a person box |
| OBJECT_DET_CONF | 0.55 | min confidence for a non-weapon object event |
| WEAPON_DET_CONF | 0.40 | weapons intentionally lower — recall matters; every weapon event with conf < 0.60 gets `requires_human_review=true` |
| FACE_DET_CONF | 0.50 | SCRFD threshold |
| FACE_MIN_PX | 40 | min face box side in pixels; smaller faces → no embedding, no gender estimate |
| GENDER_CONF_MIN | 0.80 | below → `gender_estimate='unknown'` |
| REID_MERGE_COS | 0.60 | cosine ≥ 0.60 between track face embeddings → same person (merge across cuts/videos) |
| SUSPECT_MATCH_COS | 0.65 | ≥ 0.65 → verdict `match` |
| SUSPECT_POSSIBLE_COS | 0.50 | 0.50–0.65 → `possible_match`; < 0.50 → `no_match` |
| INTERACTION_IOU_DIST | boxes within 1.5× person-width for ≥ 0.6 s | triggers `close_approach` candidate |
| REVIEW_BAND | conf in [0.40, 0.70) | any event in this band → `requires_human_review=true` |

**Processing steps (exact, per video, then case-level merge):**
1. Load frames sequentially; run YOLOv8m `track()` with ByteTrack → per-frame person boxes with persistent `track_id`. Reset tracker at each `scene_change` event from Stage 1.
2. Run weapons model on every frame; run COCO-object filtering from step 1's detections (non-person classes).
3. For every person box, run SCRFD; for faces ≥ FACE_MIN_PX, compute ArcFace embedding + genderage. Keep, per track, the top-3 quality faces (quality = det_conf × face_px_area) and their embeddings.
4. **Track → Person merge (re-identification):** greedy agglomerative merge of tracks whose best-face embeddings have cosine ≥ REID_MERGE_COS, across cuts and across all videos in the case. Tracks with no usable face are merged only if they are temporally contiguous at a cut boundary with IoU ≥ 0.5 and matching OpenCLIP appearance vector cosine ≥ 0.85; otherwise they remain separate persons (over-counting is safer than wrongly merging — the narrative must state this caveat; Stage 3 receives `face_visible=false` persons). Assign labels 'A','B',… by first appearance. Person gender = argmax over per-face gender votes weighted by confidence; apply GENDER_CONF_MIN.
5. **Action labeling per person:** compute per-track kinematics (normalized centroid speed, box aspect ratio). Rules: speed > 0.25 width/s → `running`; 0.05–0.25 → `walking`; < 0.05 sustained 3 s → `standing`; aspect ratio flip w>h → `lying_down` (person_down suspicious flag if sustained > 5 s); confirm/refine with OpenCLIP zero-shot on 1 keyframe per 2 s against the action vocabulary; emit an `action` event whenever the label changes, with confidence = mean(det conf, CLIP softmax).
6. **Interaction detection:** for each pair of persons, when proximity rule (INTERACTION_IOU_DIST) fires → candidate. Classify: overlapping boxes + high limb-region motion (frame-diff energy in the union box > 2× scene mean) → `physical_contact`/`struggle`; one leaves fast while other follows within 1 s → `pursuit`; sustained proximity, low motion → `conversation_posture`. **Direction attribution rule (who acted on whom):** actor = the person whose centroid moved toward the other with greater speed in the 1 s before contact; if speed difference < 30%, direction is `null` — the event still records both labels but `description` must say "mutual/unclear initiation" and `requires_human_review=true`. Confidence for interactions is capped at 0.75 by design — the pipeline can never claim near-certainty about intent from pixels.
7. **Appearance description:** OpenCLIP zero-shot over fixed prompt bank ("a person wearing a red jacket", … ~120 prompts covering garment type × color, headwear, bags); keep prompts with softmax > 0.3, join top 3 into `appearance_description`.
8. **Suspect matching:** for each `suspect_references` row: cosine of reference embedding vs every person's top-3 embeddings (take max). Apply SUSPECT_MATCH_COS / SUSPECT_POSSIBLE_COS → write one `suspect_match_results` row per person (including `no_match`), with `best_frame_ms` and side-by-side crop. Persons with `face_visible=false` get verdict `no_match` with `cosine_similarity=NULL`-equivalent `-1` and description "no usable face — cannot compare"; UI must show this caveat. Matching can also be triggered post-hoc via API (Section 5) if the reference is uploaded after processing — same task, incremental.
9. **Suspicious-activity flags:** rule layer emitting `suspicious_flag` events: weapon event (`weapon_visible`), `person_down`, loitering (same person, same 10%-of-frame region > 120 s), concealment (person picks up object → object disappears from view while person present: object track ends inside person box), `rapid_group_dispersal` (≥3 persons' speed > running threshold within 2 s window), forced-entry indicators (repeated arm motion at door/window region — door region from OpenCLIP scene query). Each flag cites its underlying events' frames.
10. Write all rows to Postgres, crops/frames to S3, build Timeline JSON (3.10) with `counts` computed from persons, validate against Pydantic schema, upload to S3, audit `pipeline.stage2.complete`, advance to Stage 3.

**Error handling:** GPU OOM → halve batch size and retry once, then fail with actionable reason. If **zero persons detected** in all media: still produce a valid timeline (empty persons, counts zero) — Stage 3 must then produce a scene-only narrative stating no persons were detected; this is a valid outcome, not an error. Per-frame model exceptions: skip frame, count them; if > 5% frames fail → append `quality_notes: ["frame_processing_errors"]`.

**Edge cases:** crowds (> 30 concurrent persons → keep top 30 tracks by duration, add evidence gap note "additional persons present but not individually tracked"); identical twins/uniforms (embedding merge may wrongly merge — mitigation: never merge two tracks that overlap in time in the same video, they are provably different people); person leaving and returning in different clothing (face-based merge handles it if face visible; otherwise counted as new person — caveat auto-added).

### Stage 3 — Narrative / Story Generation Engine (core feature)

**Input:** Timeline JSON + `cases.context_description` + video `quality_notes`.
**Output:** Narrative JSON (3.11) stored on the case; `ai.narrative.generated` + one `ai.claim.created` audit row per cited claim.

**Exact call structure (Anthropic Messages API, model `claude-fable-5`, temperature 0.2, max_tokens 8000):**

**System prompt (store verbatim at `backend/app/prompts/narrative.txt`):**

```
You are the narrative engine of CrimeScene AI, a decision-support tool for trained
police investigators. You write incident narratives STRICTLY from the structured
evidence timeline provided. You are not a witness and you have not seen the video;
the timeline is your only evidence.

ABSOLUTE RULES — violating any of these is a critical failure:
1. EVERY factual claim must cite at least one event id and its confidence, using
   exactly this token format: [e:<event_id>, conf <0.xx>] placed immediately after
   the claim. A sentence with no citation may contain only transitions or
   explicitly-labeled uncertainty.
2. NEVER state as fact anything not present in the timeline. The investigator's
   context description is a HYPOTHESIS to evaluate against the evidence — you may
   say the evidence "is consistent with" or "does not support" it, never adopt it.
3. Intent, guilt, motive, emotion, and identity are NEVER stated as fact. You may
   describe observable behavior only. Say "Person A" etc.; never invent names.
4. Attack/aggression claims ("A attacked B") are permitted ONLY when the timeline
   contains an interaction event with both persons, a physical_contact or struggle
   label, a non-null actor direction, and confidence >= 0.60 — and even then phrase
   as "the footage shows Person A making contact with Person B, consistent with a
   strike" with citation. If direction is unclear or confidence < 0.60, you MUST
   explicitly write that the footage does not establish who initiated contact.
5. Any event with requires_human_review=true must be described with an explicit
   uncertainty marker: "requires human review".
6. Events with confidence < 0.40 must not be used at all.
7. Where timeline gaps or quality_notes limit what can be known, say so explicitly
   in evidence_gaps.
8. Gender estimates are estimates; report the counts given, note the 'unknown'
   bucket, and never describe gender as certain.
9. Output ONLY valid JSON matching the schema provided. No markdown, no preamble.
```

**User message (exact template):**

```
<case_context_hypothesis>
{cases.context_description}
</case_context_hypothesis>

<timeline>
{Timeline JSON, minified}
</timeline>

<output_schema>
{JSON Schema of Narrative JSON, 3.11}
</output_schema>

Write the complete narrative now. Cover: (a) chronological narrative_sections
spanning the full footage; (b) one person_summary per person describing everything
that person did; (c) suspicious_activity_summary; (d) uncertainties; (e)
evidence_gaps. Timestamps in text as MM:SS.
```

**Post-processing validation (deterministic, in code — do not trust the model):**
1. Parse JSON; on parse failure retry once with the error appended; second failure → case `failed` with reason `narrative_invalid_json`.
2. Verify every citation token references a real event id in the timeline; strip any sentence containing an unknown citation and log `narrative_citation_stripped` to audit.
3. Verify no event with confidence < 0.40 is cited; verify every person label mentioned exists.
4. Regex-scan for forbidden assertive phrases without nearby citation (`"attacked"`, `"assaulted"`, `"stole"`, `"intended"`, `"guilty"`): if found uncited or citing an event that fails rule 4's criteria, replace the sentence with the templated uncertainty sentence: `"The footage does not conclusively establish this; human review required."` and audit it.
5. Inject the exact disclaimer (Section 7.5) into `disclaimer` (never trust the model to include it).
6. Copy each person_summary into `persons.activity_summary`. Write one `ai.claim.created` audit row per (claim sentence, cited events) pair.
7. Token-budget guard: if minified timeline > 150k tokens (huge cases), pre-compress deterministically in code before the call: merge consecutive identical `action` events per person (keep first/last ms, min confidence), drop `no_match` suspect entries, drop events with conf < 0.40. This compression is lossless with respect to what the model is allowed to cite.

**Error handling:** Anthropic API 429/5xx → Celery retry, backoff 30/60/120 s, max 5. Overloaded after retries → case `failed`, reason `llm_unavailable`, user-visible "Narrative generation temporarily unavailable — retry from case page" (a `POST /cases/{id}/narrative/regenerate` exists, Section 5).

**Edge cases:** empty timeline (no persons) → prompt proceeds; narrative describes scene, states no persons detected. Photos-only case → narrative describes the static scene(s); no temporal claims allowed (validated: with 1-frame media, ban words "then/after/before" between events of the same photo — implemented as a note in the user message: "MEDIA IS STATIC PHOTOS: make no sequence claims within a photo").

### Stage 4 — Interactive Q&A

**Input:** user question, `case_id`.
**Output:** assistant `ChatMessage` with citations, streamed? — **No: v1 is non-streaming** (simpler; answers are ≤ 2000 tokens).

**Context assembly for every question (exact order in the API call):**
1. System prompt `prompts/qa.txt`: identical rules 1–9 from Stage 3 plus: `"Answer the investigator's question using ONLY the timeline, the generated narrative, and this conversation. If the answer is not determinable from the evidence, say exactly that and suggest what footage or review would resolve it. Answer in markdown, concise, citations mandatory in the same [e:..., conf ...] format."`
2. `<narrative>` — current Narrative JSON (post-human-edits version: rejected claims removed, edited text substituted, so the AI never re-asserts what a human rejected).
3. `<timeline>` — compressed timeline (same deterministic compressor as Stage 3 step 7).
4. `<chat_history>` — see management below.
5. The new user question.

**Context-length management (exact policy):** budget = 160k tokens input. Priority order if over budget: (1) keep system + narrative + question always; (2) timeline gets progressively compressed (drop `evidence_frame_s3_keys`, then merge action runs, then drop conf < 0.50 non-suspicious events — never drop suspicious or interaction events); (3) chat history: keep the last 10 messages verbatim; older messages are replaced by a rolling summary generated with `claude-haiku-4-5-20251001` (prompt: "Summarize this investigator Q&A exchange in ≤300 words, preserving every cited event id"), stored in `chat_summaries` keyed by `up_to_message_id`, regenerated every 10 messages. The summary is inserted as one `assistant` context block labeled `<earlier_conversation_summary>`.

**Post-processing:** same citation validation as Stage 3 (steps 2–4). Store extracted citations in `chat_messages.citations`. Audit `ai.chat.answer` with question, answer hash, cited event ids, model id.

**Error handling:** LLM failure → HTTP 503 with `{"error":"qa_unavailable","retry_after_s":30}`; the user message is still stored so history isn't lost.

### Stage 5 — Human Review & Export

**What the investigator can do (exact operations):**
- Per timeline event: **approve** (`review_status='approved'`), **reject** (`'rejected'` — event is excluded from future narrative regenerations, Q&A context, and exports; still stored + audit-visible), **edit** (`'edited'` + `human_note`; the AI text is never overwritten — the note is displayed alongside).
- Per narrative section / person summary: edit text (stored as `human_note`-style overlay in `narrative_json` under `human_edits: [{path, original_text, edited_text, edited_by, edited_at}]` — original always preserved).
- Per suspect match: **confirm** or **reject** (`suspect_match_results.review_status`). Only a *confirmed* match may appear in an export as a match; unconfirmed shows as "unconfirmed algorithmic similarity".
- Per person: correct `gender_estimate` (recorded as human override, both values kept), rename label's display alias (e.g., "A (victim)") — the canonical letter label never changes.
- Regenerate narrative after review (`POST /cases/{id}/narrative/regenerate`) — Stage 3 reruns with rejected events excluded and human notes appended to the user message as `<human_review_notes>`.

**Export report (PDF via WeasyPrint) — exact contents in order:** cover page (case number/title, generating user, timestamp, report sha256, **disclaimer** in a bordered box); case metadata + media inventory with sha256 hashes (chain of custody); narrative (with citation chips rendered as `[00:51, conf 0.64]`); People section (face crop or silhouette, label, presence intervals, gender estimate + confidence + any human override, activity summary); person counts table; suspicious activity section with evidence frame images; object detections table; suspect match section (side-by-side photos, similarity, verdict, human confirmation status); uncertainties & evidence gaps section (mandatory, never omitted); optional full Q&A transcript; review log (every approve/reject/edit with user + timestamp); disclaimer repeated on the final page footer of every page.

**AI vs human provenance logging:** every element in the export carries a provenance tag rendered in the PDF margin: `AI` (unreviewed), `AI✓` (approved), `AI✎` (edited — both versions shown), `H` (human-added note). The export `snapshot` JSONB freezes everything; exports are immutable (re-export = new row, new sha256).

---

## 5. API CONTRACT

Base path `/api/v1`. All endpoints require `Authorization: Bearer <JWT>` except `/auth/login`. All errors: `{"error": "<machine_code>", "message": "<human text>"}` with appropriate 4xx/5xx. All list endpoints paginate with `?page=1&page_size=50` and return `{"items": [...], "total": n, "page": 1, "page_size": 50}`.

**Auth** (JWT access token 30 min + refresh token 12 h, httpOnly cookie for refresh; argon2id password hashing; TOTP MFA step when enrolled):

| Method & path | Request body | Response |
|---|---|---|
| POST `/auth/login` | `{"email", "password", "totp_code?"}` | `{"access_token", "expires_in", "user": {id, full_name, role}}` (+ refresh cookie) |
| POST `/auth/refresh` | – (cookie) | same as login |
| POST `/auth/logout` | – | 204 |
| GET `/auth/me` | – | user object |

**Cases:**

| Method & path | Request | Response |
|---|---|---|
| POST `/cases` | `{"case_number","title","context_description"}` | Case object (status `created`) |
| GET `/cases` | query: `page,page_size,status?,q?` | paginated Case list (each with person_count_total, status, created_at) |
| GET `/cases/{id}` | – | full Case incl. narrative_json, counts, videos |
| PATCH `/cases/{id}` | any of `{"title","context_description"}` | Case |
| DELETE `/cases/{id}` | – | 204 (soft-archive; hard purge only via retention job or admin `?hard=true`, double-audited) |
| GET `/cases/{id}/status` | – | `{"status","stage_progress_pct","stage","failure_reason"}` (reads Redis; poll every 3 s) |

**Media upload (pre-signed flow):**

| Method & path | Request | Response |
|---|---|---|
| POST `/cases/{id}/media` | `{"filename","media_type","content_type","size_bytes","sha256"}` | `{"video_id","upload_url","s3_key"}` (pre-signed PUT, 15 min) |
| POST `/cases/{id}/media/{video_id}/complete` | – | 200; when client calls this for the last file it also passes `{"start_processing": true}` → enqueues pipeline, status `queued`. 409 on duplicate sha256. |
| GET `/cases/{id}/media` | – | list of Video objects with pre-signed GET urls for normalized video |

**Results retrieval:**

| Method & path | Response |
|---|---|
| GET `/cases/{id}/persons` | `[Person]` each with pre-signed face/body crop URLs, gender + confidence, presence intervals, activity_summary, suspect match badge |
| GET `/cases/{id}/timeline` | query `?person_label=&event_type=&suspicious_only=&from_ms=&to_ms=` → paginated `[TimelineEvent]` with pre-signed evidence frame URLs |
| GET `/cases/{id}/narrative` | Narrative JSON (with human_edits overlay) |
| POST `/cases/{id}/narrative/regenerate` | 202 `{"job":"queued"}` (re-runs Stage 3 honoring review state) |

**Review (Stage 5):**

| Method & path | Request | Response |
|---|---|---|
| POST `/cases/{id}/events/{event_id}/review` | `{"action":"approve"\|"reject"\|"edit","human_note?"}` | updated event |
| POST `/cases/{id}/narrative/edits` | `{"path":"narrative_sections[2].text","edited_text"}` | updated narrative_json |
| POST `/cases/{id}/persons/{person_id}/override` | `{"gender_estimate?","display_alias?"}` | updated person |

**Suspect matching:**

| Method & path | Request | Response |
|---|---|---|
| POST `/cases/{id}/suspects` | `{"display_name","filename","content_type","size_bytes","sha256"}` | `{"suspect_reference_id","upload_url"}` |
| POST `/cases/{id}/suspects/{ref_id}/complete` | – | 202; validates face present (422 `no_face_detected` if not), runs matching (immediate if case already processed, else joins pipeline) |
| GET `/cases/{id}/suspects` | – | `[{reference, results: [SuspectMatchResult + person summary + side-by-side crop URLs]}]` |
| POST `/cases/{id}/suspects/{ref_id}/results/{result_id}/review` | `{"action":"confirm"\|"reject"}` | updated result |

**Chat / Q&A:**

| Method & path | Request | Response |
|---|---|---|
| POST `/cases/{id}/chat` | `{"question"}` | `{"message": ChatMessage(assistant), "citations":[...]}` (synchronous, ≤ 60 s timeout) |
| GET `/cases/{id}/chat` | paginated | `[ChatMessage]` oldest-first |

**Export:**

| Method & path | Request | Response |
|---|---|---|
| POST `/cases/{id}/exports` | `{"includes_chat": bool}` | 202 `{"export_id"}` (Celery task builds PDF) |
| GET `/cases/{id}/exports` | – | `[{export_id, created_at, generated_by, sha256, status}]` |
| GET `/cases/{id}/exports/{export_id}/download` | – | 302 to pre-signed PDF URL; audits `export.downloaded` |

**Audit (supervisor/admin only):** GET `/cases/{id}/audit` and GET `/audit` — paginated, filter by action/actor/date.

---

## 6. FRONTEND SCREEN MAP

Routing (React Router): all under auth guard except `/login`.

| Route | Screen | Contents & backend state |
|---|---|---|
| `/login` | Login | email/password (+TOTP). State: none. → `/cases` |
| `/cases` | Case List | table: case_number, title, status pill, person count, created; search + status filter; "New Case" button. State: `GET /cases` (poll 10 s for rows in processing states). Row click → `/cases/{id}` (or status screen if not complete). |
| `/cases/new` | New Case / Upload | 3-step wizard: (1) case_number/title/context_description form; (2) drag-drop media, per-file progress bars using pre-signed PUT, client computes sha256 (WebCrypto); (3) optional suspect reference photo upload; "Start Analysis" → complete endpoints. State: `POST /cases`, media endpoints. |
| `/cases/{id}/processing` | Processing Status | stage stepper (Uploading → Queued → Ingesting → Detecting → Narrating → Complete) with percent + elapsed; failure state shows failure_reason + retry button. State: `GET /cases/{id}/status` poll 3 s; auto-navigate to dashboard on complete. |
| `/cases/{id}` | Case Dashboard shell | header (case meta, status, Export button, disclaimer banner — always visible, Section 7.5 short form); left tab nav to the sub-views below; right side persistent **Chat Q&A panel** (collapsible) on every tab. |
| `/cases/{id}` (default tab) | **Narrative / Story view** | video player (normalized mp4) on top; narrative sections below with citation chips `[00:51 · 64%]` — click seeks player and highlights bbox overlay for that event; uncertainty blocks styled amber with "REQUIRES HUMAN REVIEW" badge; evidence-gaps panel; "Regenerate narrative" button (enabled after review actions). State: `GET /narrative`, `GET /media`, `GET /timeline` (for chip → event lookup). |
| `…/people` | **People section** (dedicated, required) | card grid: face crop (or silhouette + "face not visible"), big letter label A/B/C, display alias editor, gender estimate + confidence bar (or "unknown"), presence intervals as mini-timeline, activity_summary, suspect-match badge if any; header shows **total count** and **male/female/unknown breakdown**; card click → filtered timeline for that person + "show in player" jumping to first_seen. State: `GET /persons`. |
| `…/timeline` | Timeline view | horizontal zoomable timeline lanes (one per person + one objects lane + one flags lane); event blocks colored by type, red = suspicious, amber outline = requires review; click → detail drawer (evidence frames, bbox image, confidence, approve/reject/edit buttons). Filters: person, type, suspicious-only. State: `GET /timeline` with filters. |
| `…/flags` | **Suspicious Activity view** | list of `suspicious_flag` + suspicious events sorted by severity (weapon > person_down > struggle > others), each with evidence frame strip, confidence, jump-to-player, review buttons. State: `GET /timeline?suspicious_only=true`. |
| `…/objects` | **Object Detection view** | grid grouped by object_class; thumbnails from evidence frames; per-detection confidence + timestamps; weapons pinned to top with red banner. State: `GET /timeline?event_type=object_detection`. |
| `…/suspect` | **Suspect Match view** | upload zone for reference photo; per reference: side-by-side comparison (reference vs best footage crop), similarity score with verdict pill (`MATCH` / `POSSIBLE` / `NO MATCH`), timestamps of appearances, confirm/reject buttons; mandatory caption "Algorithmic similarity — not identity confirmation" under every result. State: suspect endpoints. |
| `…/review` | Review & Export | tallies (unreviewed/approved/rejected/edited); table of all `requires_human_review` items first; export panel: include-chat toggle, "Generate PDF", list of prior exports with download + sha256. Supervisors see approve-export gate here. State: timeline + exports endpoints. |
| (panel) | Chat Q&A panel | message list with citation chips (same click-to-seek behavior), input box, "answer pending" spinner; empty-state suggests example questions. State: `GET/POST /cases/{id}/chat`. |
| `/admin` | Admin (role-gated) | user management CRUD, retention policy setting, audit log browser. |

Global UI rules: every confidence is always displayed next to its claim (Section 7.1); no screen ever shows an AI claim without its chip; deleting anything requires typed confirmation.

---

## 7. SAFETY, ACCURACY & LEGAL GUARDRAILS

### 7.1 Confidence surfacing rules (exact)
1. Every AI-generated claim visible in the UI or an export carries its numeric confidence (rendered as a percentage chip) and its timestamp citation. No exceptions — a claim without a chip is a UI bug.
2. Color bands, fixed: conf ≥ 0.70 neutral gray chip; 0.40–0.69 amber chip + "requires human review" tooltip; < 0.40 never displayed as a claim anywhere (only visible in the raw timeline with an explicit "below evidentiary threshold — not used in analysis" watermark).
3. Aggregates (person count, gender breakdown) display the weakest underlying confidence: e.g., "4 people detected (lowest track confidence 61%)" and the unknown-gender bucket is always shown, never folded into male/female.
4. Suspect match results always show the raw similarity score alongside the verdict, plus the fixed caption in 6's Suspect view. Verdict language is constrained to: "match (algorithmic)", "possible match (algorithmic)", "no match found". The word "identified" is banned in UI copy and prompts.

### 7.2 What the AI may state vs must flag (exact rules — enforced in prompts AND in deterministic post-validation, Section 4 Stage 3)
**Never stateable as fact:** identity ("this is John Doe"), intent/motive ("meant to", "in order to"), guilt or crime legal categories ("assault", "theft", "murder" as conclusions), emotion ("angrily"), anything from the investigator's context description not independently present in the timeline, anything about off-camera time, gender as certainty, audio content (no audio analysis in v1).
**Stateable with citation:** observable positions, movements, contacts, object presence, timing, appearance descriptions — phrased as what "the footage shows".
**Attack-attribution rule (restated as the governing rule):** "A attacked B" class claims require interaction event + both persons + contact/struggle label + non-null actor direction + conf ≥ 0.60, phrased as "consistent with a strike", cited; otherwise the narrative MUST contain the explicit sentence that initiation cannot be established from the footage.
**Ambiguity handling:** any `requires_human_review` event may only appear with its uncertainty marker; the `uncertainties` section of the narrative is mandatory and may not be empty if any such events exist.

### 7.3 Data retention & privacy
- All media and face data encrypted at rest (S3 SSE + Postgres full-disk encryption assumption; `mfa_totp_secret` and any future PII columns app-encrypted with AES-GCM).
- TLS 1.2+ everywhere in transit; pre-signed URLs 15-min expiry.
- Retention: per-deployment default 365 days (`RETENTION_DAYS` env). Nightly Celery beat job: cases past `retention_expires_at` → hard purge (S3 delete incl. all crops/frames/embeddings, DB rows deleted, `retention.purge` audit row kept). Supervisors can extend retention per case (audited) for active proceedings.
- Face embeddings and crops are biometric data: they exist only inside the case that produced them; **no cross-case face search of any kind** (explicit v1 product decision — a reference photo is matched only within its own case). No model training on customer data. No third-party calls except the Anthropic API, which receives only the structured timeline text and narrative — **never raw images, frames, or face crops** (v1 is text-only to the LLM; this is also why detection quality matters).
- Access control: media URLs only issued to case members; every media view audited (`media.view`).
- Right-to-erasure/admin purge: admin hard-delete performs the same purge path; audit rows persist (lawful-basis record) but contain no media.

### 7.4 Audit logging requirements (per AI claim)
Every `ai.claim.created` audit row's `detail` MUST contain: `{claim_text, claim_type (narrative_sentence|person_summary|suspicious_summary|chat_answer|match_verdict), cited_event_ids[], confidences[], model_id, prompt_sha256, timeline_sha256, generated_at}`. Additionally logged: every review action with before/after, every export with snapshot hash, every login/failed login, every media view/download, every deletion. The `prev_row_sha256` hash chain (3.9) makes tampering evident; a nightly job verifies the chain and alerts on break.

### 7.5 Mandatory disclaimer (exact text — constant `LEGAL_DISCLAIMER`)
> **AI-Assisted Analysis — Not Evidence.** This content was generated by CrimeScene AI, an automated analysis tool, from the referenced footage. It is investigative decision support only. It may contain errors, including missed persons or objects, incorrect tracking, and mistaken interpretation of events. Every statement carries a confidence score and timestamp citation and must be independently verified by a qualified human investigator against the original footage before any investigative, prosecutorial, or legal use. Person labels (A, B, C…) are anonymous tracking labels, not identifications. Gender values are algorithmic estimates. Suspect-match results indicate algorithmic facial similarity only and do not constitute identification. This output is not a statement of fact, guilt, or legal conclusion.

Rendered: full text on every export cover + final page; condensed banner ("AI-assisted analysis — verify against footage before use. Not evidence.") pinned atop every case dashboard tab and above every chat answer.

---

## 8. BUILD ORDER / MILESTONES

Each phase is independently completable and testable. The implementing model executes them in order and must not start a phase before the previous phase's done-criteria pass.

**Phase 0 — Scaffolding & infrastructure.** Deliverable: monorepo per Section 2 layout; `docker-compose.yml` bringing up postgres/redis/minio/api/frontend; FastAPI app with `/healthz`; Alembic wired; React app with router + login placeholder; CI running `pytest` + `npm test` + linters. Done when: `docker compose up` serves frontend at :3000, API `/healthz` 200, alembic migration runs. Test data: none.

**Phase 1 — Auth, users, cases CRUD, audit skeleton.** Files: `models/{user,case,audit}.py`, `api/{auth,cases,audit}.py`, `services/audit.py` (with hash chain), login page, case list/new-case form (no upload yet). Done when: create user via CLI seed script, login, create/list/patch case; every action produces a chained audit row; chain-verify script passes. Test data: `scripts/seed.py` creating 3 users (one per role) and 2 cases.

**Phase 2 — Media upload + Stage 1.** Files: `api/media.py`, `pipeline/stage1.py`, celery app, MinIO bucket bootstrap, upload wizard UI, processing-status screen + polling. Done when: uploading `tests/fixtures/sample_10s.mp4` (add a ~10 s 720p clip with 2 people; also `sample_photo.jpg`) yields frames in MinIO, populated `videos` row, status transitions visible in UI; photo path yields 1 frame; corrupt file yields `failed` with reason. Test data: the two fixtures + a deliberately corrupt file.

**Phase 3 — Timeline data layer + FAKE detector.** Files: `models/{person,timeline_event}.py`, `schemas/timeline.py` (Pydantic `CaseTimeline`, exact 3.10), `pipeline/stage2_fake.py` — a stub that, when env `PIPELINE_FAKE=1`, writes a **hand-authored fixture timeline** `tests/fixtures/timeline_fixture.json` (author it to contain: 3 persons incl. one `face_visible=false`, one interaction with unclear direction, one weapon at conf 0.47, one loitering flag — i.e., every branch Stage 3 must handle) into DB/S3. Also `api` endpoints `GET /persons`, `GET /timeline`, and the People/Timeline/Flags/Objects UI tabs rendering from it. Done when: full UI renders the fixture case correctly, filters work, counts and unknown-gender bucket display. **This fixture is the contract test that lets Stage 3 be built before real CV exists.**
 
**Phase 4 — Stage 3 narrative engine against the fixture.** Files: `pipeline/stage3.py`, `prompts/narrative.txt` (verbatim Section 4), post-validation module `pipeline/narrative_guard.py`, narrative UI tab with citation chips + player seek. Done when: running the pipeline on the Phase 3 fixture produces a schema-valid narrative where (a) every claim has a valid citation, (b) the unclear-direction interaction is described as unestablished, (c) the 0.47 weapon appears with review flag, (d) disclaimer injected; `narrative_guard` unit tests cover the forbidden-phrase and bad-citation paths with canned LLM outputs. Test data: 3 canned "bad LLM responses" (invalid JSON, fake citation, uncited "attacked") checked into `tests/fixtures/llm_bad/`.

**Phase 5 — Real Stage 2 (CV).** Files: `pipeline/stage2.py`, `pipeline/thresholds.py`, model weights fetched by `scripts/fetch_models.py` into a mounted `models/` volume; `docker-compose.gpu.yml`. Done when: `sample_10s.mp4` end-to-end (no `PIPELINE_FAKE`) produces ≥ 2 persons with face crops, plausible actions, a valid Timeline JSON passing the same Pydantic schema, and the narrative renders; photo case works; zero-person clip (add fixture `empty_street.mp4`) completes with empty-persons narrative. Test data: `sample_10s.mp4`, `empty_street.mp4`, plus a clip with a visible knife prop for weapon-path testing (source/record one; flagged in Section 9 if unavailable, substitute COCO `knife` on a kitchen clip).

**Phase 6 — Suspect matching.** Files: `models/suspect.py`, `api/suspects.py`, matching logic in stage2 + post-hoc task, Suspect Match UI tab. Done when: uploading a reference photo of a person in `sample_10s.mp4` yields `match` ≥ 0.65 with side-by-side; an unrelated face yields `no_match`; a no-face image yields 422. Test data: two reference photos (one of a person in the sample clip, one stranger — use permissively-licensed face photos or self-recorded).

**Phase 7 — Q&A.** Files: `api/chat.py`, `services/chat_context.py` (budget policy of Stage 4 verbatim), `prompts/qa.txt`, chat panel UI. Done when: questions about the fixture case return cited answers; a question with no evidentiary answer returns the "not determinable" phrasing; 25-message conversation triggers and uses a `chat_summaries` row (assert via test). Test data: scripted 25-question pytest conversation against the Phase 3 fixture (run with fake LLM responder for CI + one live smoke test).

**Phase 8 — Review & export.** Files: review endpoints, `services/export.py` + Jinja2/WeasyPrint template, Review UI, provenance tags, regenerate-narrative flow. Done when: reject an event → regenerate → event absent from narrative and Q&A context; PDF contains every Section 4 Stage 5 element incl. disclaimers, provenance margins, sha256 footer; export snapshot immutable after further edits. Test data: reuse fixture case; golden-file test on PDF text layer.

**Phase 9 — Retention, hardening, deployment.** Files: celery-beat retention job, chain-verify job, rate limiting (slowapi: 10 login/min, 60 req/min general), security headers, MFA enrollment UI, prod compose profile with TLS notes, load smoke test (3 concurrent case processings). Done when: retention job purges an expired seeded case incl. S3 objects; chain-verify passes; OWASP-baseline ZAP scan shows no high findings.

---

## 9. OPEN RISKS AND ASSUMPTIONS

**Technical risks (with mitigations in place):**
1. **Tracking/re-ID accuracy on low-quality CCTV** — ByteTrack + face merge degrades badly at low light/resolution; person count may over-count (by design we prefer over-count + caveat to wrong merges). Mitigation: quality_notes propagate into narrative caveats; review UI. Residual risk: high on sub-480p night footage.
2. **Narrative hallucination** — mitigated by citation-mandatory prompting + deterministic post-validation stripping uncited claims; residual risk: subtly wrong but validly-cited paraphrase; human review is the backstop.
3. **Latency** — 60-min video at 3 fps ≈ 10.8k frames; Stage 2 on one A10G ≈ 15–30 min. Acceptable for v1 (async + status screen), but concurrent cases queue behind one GPU. Scale-out is a later phase.
4. **Gender-estimation accuracy/bias** — InsightFace genderage has documented demographic error skew. Mitigations: 0.80 threshold, mandatory 'unknown' bucket, never-certain phrasing, human override. Residual: counts are estimates; the UI says so.
5. **Face-matching accuracy/bias** — ArcFace similarity varies across demographics and degrades with pose/resolution; 0.65 threshold chosen conservative for CCTV. All matches require human confirmation before export. Residual risk remains and is disclosed in the disclaimer.
6. **Action/interaction classification is heuristic + CLIP** (no dedicated video-action model in v1) — interactions capped at 0.75 confidence and review-flagged in the 0.40–0.70 band. Risk: missed subtle actions (e.g., pickpocketing).
7. **Weapon detection false negatives/positives** — small objects at CCTV distance; 0.40 threshold trades precision for recall, review-flagged.
8. **LLM context limits on very long/multi-camera cases** — deterministic timeline compression may drop nuance; monitored via token logging.
9. **No audio analysis in v1** — gunshots/speech unanalyzed (stored for humans). Explicit deferral.

**Assumptions to confirm before build:**
1. Deployment may be on-prem/air-gapped for the CV stack, but **the Anthropic API requires outbound internet** — assumed acceptable; if fully air-gapped is required, narrative/Q&A needs a self-hosted model decision (out of scope of this doc).
2. Sending timeline **text** (no images/biometrics) to the Anthropic API is acceptable under the customer's data-handling rules; a zero-retention agreement with the API provider is assumed to be arranged.
3. English-only UI and narratives in v1.
4. Retention default 365 days; jurisdictional evidence-retention law may require different values — configurable, but the default needs legal confirmation.
5. Single-tenant per deployment (one bureau per instance); no multi-tenancy isolation built.
6. Cross-case face search deliberately excluded (privacy stance) — confirm this matches product intent.
7. Max limits (4 GB/file, 60 min/video, 20 files/case, 30 tracked persons) are assumed acceptable operational bounds.
8. Browser support: current Chrome/Edge/Firefox only.
9. A licensed/lawful weapons-detection training dataset and test clips can be obtained; otherwise weapon detection ships COCO-knife-only at first.
10. This tool will be operated only by authorized law-enforcement personnel under applicable law (biometric-processing legal basis, e.g. GDPR Art. 10/LED in the EU, is the operator's responsibility); the system enforces technical controls (audit, retention, access) but not legal authorization itself.

---

ARCHITECTURE COMPLETE — READY TO BUILD
