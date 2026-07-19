# CrimeScene AI

AI-powered investigation co-pilot for police, investigation bureaus, and forensic teams.
Upload crime-scene/CCTV footage plus a short context description; the system produces a
fully evidence-cited case summary — narrative story, detected people (anonymous labels
A/B/C…), person counts and gender estimates, per-person activity, suspicious-activity
flags, object/weapon detections, suspect reference-photo matching — and an interactive
Q&A chat. Every claim carries a timestamp citation and confidence score; ambiguity is
flagged for human review, never guessed.

> **Decision support only.** This tool assists human investigators. It is never a sole or
> final source of legal truth or evidence. All output must be verified by a qualified
> investigator against the original footage before any use.

The complete technical specification is in [ARCHITECTURE.md](ARCHITECTURE.md).

## Repository layout

```
backend/    FastAPI API + Celery pipeline (Python 3.12)
frontend/   React 18 + TypeScript SPA (Vite, Tailwind, TanStack Query)
deploy/     docker-compose stack (postgres+pgvector, redis, minio, api, workers, frontend)
models/     CV model weights (fetched by scripts/fetch_models.py; not committed)
```

## Quick start (full demo, no GPU / no API key)

```bash
cd deploy
cp .env.example .env          # defaults enable PIPELINE_FAKE + LLM_FAKE
docker compose up --build
```

- Frontend: http://localhost:3000 — log in as `investigator@example.gov` / `Password123!`
  (also `supervisor@` and `admin@`, same password; seeded by `scripts/seed.py`).
- API docs: http://localhost:8000/api/docs
- MinIO console: http://localhost:9001

Create a case, upload any short mp4 or a photo, start analysis. In fake mode Stage 2
loads the hand-authored fixture timeline (`backend/tests/fixtures/timeline_fixture.json`)
and the LLM responder is deterministic, so the whole product — People, Timeline, Flags,
Objects, Suspect Match, Narrative, Q&A, Review, PDF export — works end-to-end offline.

## Real mode

1. `python -m scripts.fetch_models` (downloads YOLOv8m + InsightFace buffalo_l into `models/`;
   optionally place a fine-tuned `weapons_yolov8m.pt` there).
2. Set `PIPELINE_FAKE=0`, `LLM_FAKE=0`, and a real `ANTHROPIC_API_KEY` in `deploy/.env`.
3. `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build`
   (requires nvidia-container-toolkit).

## Development

```bash
# backend
cd backend && pip install -r requirements.txt && DATABASE_URL=sqlite:///:memory: pytest
# frontend
cd frontend && npm install && npm run dev   # proxies /api to localhost:8000
```

## Safety & legal guardrails (summary — full rules in ARCHITECTURE.md §7)

- Every AI claim is cited `[timestamp · confidence]`; uncited or sub-threshold claims are
  stripped by a deterministic guard before anything is stored or shown.
- "Who attacked whom" claims require an interaction event with resolved direction and
  confidence ≥ 0.60; otherwise the narrative must state that initiation is not established.
- Identity, intent, guilt, emotion are never stated as fact. Suspect matches are
  "algorithmic similarity", never identification, and require human confirmation.
- Append-only, hash-chained audit log records every AI claim, review action, view,
  export, and deletion.
- Media access only via 15-minute pre-signed URLs; retention purge is automatic; no
  cross-case face search; no raw images are ever sent to the LLM.
