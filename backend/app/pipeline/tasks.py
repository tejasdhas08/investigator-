"""Celery task entrypoints and the pipeline chain wiring.

Chain: stage1_ingest -> stage2_detect -> stage3_narrative (Section 2).
PIPELINE_FAKE=1 swaps stage2 for the hand-authored fixture detector (Phase 3).
"""
import traceback

from celery import chain

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.case import Case
from app.pipeline.celery_app import celery
from app.services import audit, progress


def start_case_pipeline(case_id: str) -> None:
    chain(stage1_task.si(case_id), stage2_task.si(case_id), stage3_task.si(case_id)).apply_async()


def enqueue_stage3(case_id: str) -> None:
    stage3_task.delay(case_id)


def enqueue_suspect_match(case_id: str, ref_id: str) -> None:
    suspect_match_task.delay(case_id, ref_id)


def enqueue_export(export_id: str) -> None:
    export_task.delay(export_id)


def _fail_case(case_id: str, reason: str) -> None:
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        if case is not None:
            case.status = "failed"
            case.failure_reason = reason[:2000]
            audit.log(db, action="pipeline.failed", actor_type="system", case_id=case.id,
                      detail={"reason": reason[:500]})
            db.commit()


@celery.task(name="app.pipeline.tasks.stage1", bind=True, max_retries=3, default_retry_delay=10)
def stage1_task(self, case_id: str):
    from app.pipeline import stage1

    try:
        stage1.run(case_id)
    except stage1.ValidationFailure as exc:  # non-retryable
        _fail_case(case_id, str(exc))
        raise RuntimeError(f"stage1 validation failure: {exc}") from exc
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            _fail_case(case_id, f"stage1 error: {exc}")
            raise
        raise self.retry(exc=exc, countdown=10 * (3 ** self.request.retries))
    return case_id


def resolve_stage2_backend():
    """Pick the detection backend (Phase 1 dispatch).

    PIPELINE_FAKE=1 forces the fixture detector (demo/CI only). Otherwise
    PIPELINE_MODE selects: 'full' (YOLOv8+InsightFace, GPU-oriented), 'lite'
    (dlib+MediaPipe, CPU/offline-capable), or 'auto' — full if available, else
    lite, else a hard failure that names exactly what's missing. Never silently
    falls back to fixture data."""
    if settings.pipeline_fake:
        from app.pipeline import stage2_fake

        return stage2_fake, "fake"
    mode = settings.pipeline_mode
    from app.pipeline import stage2, stage2_lite

    full_ok, full_why = stage2.available()
    lite_ok, lite_why = stage2_lite.available()
    if mode == "full" or (mode == "auto" and full_ok):
        if not full_ok:
            raise RuntimeError(f"full detection backend unavailable: {full_why}")
        return stage2, "full"
    if mode == "lite" or (mode == "auto" and lite_ok):
        if not lite_ok:
            raise RuntimeError(f"lite detection backend unavailable: {lite_why}")
        return stage2_lite, "lite"
    raise RuntimeError(
        f"no detection backend available — full: {full_why}; lite: {lite_why}"
    )


@celery.task(name="app.pipeline.stage2.detect", bind=True, max_retries=1)
def stage2_task(self, case_id: str):
    try:
        stage2_impl, backend = resolve_stage2_backend()
        stage2_impl.run(case_id)
    except Exception as exc:
        traceback.print_exc()
        _fail_case(case_id, f"stage2 error: {exc}")
        raise
    return case_id


@celery.task(name="app.pipeline.tasks.stage3", bind=True, max_retries=5)
def stage3_task(self, case_id: str):
    from app.pipeline import stage3

    try:
        stage3.run(case_id)
    except stage3.LLMUnavailable as exc:
        if self.request.retries >= self.max_retries:
            _fail_case(case_id, "llm_unavailable")
            raise
        raise self.retry(exc=exc, countdown=min(30 * (2 ** self.request.retries), 120))
    except Exception as exc:
        traceback.print_exc()
        _fail_case(case_id, f"stage3 error: {exc}")
        raise
    return case_id


@celery.task(name="app.pipeline.stage2.suspect_match", bind=True, max_retries=1)
def suspect_match_task(self, case_id: str, ref_id: str):
    impl, _backend = resolve_stage2_backend()
    impl.match_suspect(case_id, ref_id)


@celery.task(name="app.pipeline.tasks.export", bind=True, max_retries=2, default_retry_delay=15)
def export_task(self, export_id: str):
    from app.services import export as export_service

    export_service.build_export(export_id)


@celery.task(name="app.pipeline.tasks.retention_purge")
def retention_purge():
    from app.services.retention import purge_expired

    purge_expired()


@celery.task(name="app.pipeline.tasks.audit_chain_verify")
def audit_chain_verify():
    with SessionLocal() as db:
        ok, broken = audit.verify_chain(db)
        if not ok:
            audit.log(db, action="audit.chain_broken", actor_type="system",
                      detail={"first_broken_row_id": broken})
            db.commit()
        return {"ok": ok, "first_broken_row_id": broken}
