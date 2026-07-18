"""Audit hash chain (3.9): intact chains verify; any tampering is detected."""
from app.services import audit


def test_chain_verifies(db_session):
    for i in range(5):
        audit.log(db_session, action="case.create", actor_type="system", detail={"n": i})
    db_session.commit()
    ok, broken = audit.verify_chain(db_session)
    assert ok and broken is None


def test_tamper_detected(db_session):
    for i in range(5):
        audit.log(db_session, action="case.create", actor_type="system", detail={"n": i})
    db_session.commit()
    from app.models.audit import AuditLog

    row = db_session.query(AuditLog).filter(AuditLog.id == 3).one()
    row.detail = {"n": 999, "tampered": True}
    db_session.commit()
    ok, broken = audit.verify_chain(db_session)
    assert not ok
    assert broken in (3, 4)  # row 3's detail no longer matches; row 4's prev-hash breaks


def test_ai_claim_required_fields(db_session):
    import uuid

    row = audit.ai_claim(
        db_session, case_id=uuid.uuid4(), claim_text="Person A enters [e:x, conf 0.9].",
        claim_type="narrative_sentence", cited_event_ids=["x"], confidences=[0.9],
        model_id="claude-fable-5", prompt_sha256="p" * 64, timeline_sha256="t" * 64,
    )
    db_session.commit()
    for field in ("claim_text", "claim_type", "cited_event_ids", "confidences",
                  "model_id", "prompt_sha256", "timeline_sha256"):
        assert field in row.detail
