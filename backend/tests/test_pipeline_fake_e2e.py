"""End-to-end fake pipeline: stage2_fake (fixture) -> stage3 (fake LLM) on a real
database session. Verifies Phase 3+4 done-criteria at the integration level."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def shared_db(monkeypatch):
    from app.core.db import Base
    import app.models  # noqa: F401

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    from app.pipeline import stage2_fake, stage3
    from app.pipeline.tasks import _fail_case  # noqa: F401  (import for coverage)

    monkeypatch.setattr(stage2_fake, "SessionLocal", Session)
    monkeypatch.setattr(stage3, "SessionLocal", Session)
    monkeypatch.setattr("app.services.progress.set_progress", lambda *a, **k: None)
    monkeypatch.setattr("app.services.storage.upload_bytes", lambda *a, **k: None)
    return Session


def _seed_case(Session) -> str:
    from app.core.security import hash_password
    from app.models.case import Case
    from app.models.user import User
    from app.models.video import Video

    with Session() as db:
        user = User(email="e2e@example.gov", full_name="E2E", role="investigator",
                    password_hash=hash_password("x"))
        db.add(user)
        db.flush()
        case = Case(
            case_number="E2E-1", title="E2E", context_description="I believe A attacked B.",
            owner_id=user.id, status="detecting",
            retention_expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        )
        db.add(case)
        db.flush()
        video = Video(
            case_id=case.id, media_type="video", original_filename="cam1.mp4",
            s3_key_original="cases/x/original.mp4", sha256="0" * 64,
            s3_prefix_frames=f"cases/{case.id}/media/frames/",
            duration_seconds=184.0, fps_sampled=5.0, width=1280, height=720,
            frame_count_sampled=920, upload_complete=True, quality_notes=["low_light"],
        )
        db.add(video)
        db.commit()
        return str(case.id)


def test_fake_pipeline_end_to_end(shared_db):
    from app.pipeline import stage2_fake, stage3

    case_id = _seed_case(shared_db)
    stage2_fake.run(case_id)
    stage3.run(case_id)

    from app.models.audit import AuditLog
    from app.models.case import Case
    from app.models.person import Person
    from app.services.constants import LEGAL_DISCLAIMER

    with shared_db() as db:
        case = db.get(Case, uuid.UUID(case_id))
        assert case.status == "complete"
        assert case.person_count_total == 3
        assert case.person_count_unknown_gender == 1

        doc = case.narrative_json
        assert doc["disclaimer"] == LEGAL_DISCLAIMER
        # the context hypothesis must never be adopted as fact
        assert "attacked" not in " ".join(s["text"] for s in doc["narrative_sections"]).lower() \
            or "does not" in " ".join(s["text"] for s in doc["narrative_sections"]).lower()
        assert any("does not establish who initiated" in u["text"] for u in doc["uncertainties"])
        assert doc["person_summaries"] and len(doc["person_summaries"]) == 3

        # person activity summaries copied onto Person rows
        persons = db.query(Person).filter(Person.case_id == case.id).all()
        assert all(p.activity_summary for p in persons)

        # every AI claim audit-logged with required fields; chain intact
        claims = db.query(AuditLog).filter(AuditLog.action == "ai.claim.created").all()
        assert claims
        for c in claims:
            assert {"claim_text", "cited_event_ids", "model_id",
                    "prompt_sha256", "timeline_sha256"} <= set(c.detail)
        from app.services.audit import verify_chain

        ok, _ = verify_chain(db)
        assert ok


def test_fake_suspect_match(shared_db):
    from app.models.suspect import SuspectMatchResult, SuspectReference
    from app.models.user import User
    from app.pipeline import stage2_fake

    case_id = _seed_case(shared_db)
    stage2_fake.run(case_id)

    with shared_db() as db:
        user = db.query(User).first()
        ref = SuspectReference(case_id=uuid.UUID(case_id), uploaded_by=user.id,
                               display_name="Suspect #4411", s3_key_photo="cases/x/ref.jpg",
                               upload_complete=True)
        db.add(ref)
        db.commit()
        ref_id = str(ref.id)

    stage2_fake.match_suspect(case_id, ref_id)

    with shared_db() as db:
        results = db.query(SuspectMatchResult).all()
        assert len(results) == 3
        by_verdict = {}
        for r in results:
            by_verdict.setdefault(r.verdict, 0)
            by_verdict[r.verdict] += 1
        assert by_verdict.get("match") == 1        # Person A
        assert by_verdict.get("no_match") == 2     # B + face-not-visible C
        assert any(r.cosine_similarity == -1.0 for r in results)  # C: no usable face
