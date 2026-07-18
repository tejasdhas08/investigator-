"""Stage 5 export: immutable PDF report built from a frozen snapshot (Section 4, Stage 5)."""
import hashlib
import json
from datetime import datetime, timezone

from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.case import Case
from app.models.chat import ChatMessage
from app.models.export import ExportReport
from app.models.person import Person
from app.models.suspect import SuspectMatchResult, SuspectReference
from app.models.timeline_event import TimelineEvent
from app.models.user import User
from app.models.video import Video
from app.services import audit, storage
from app.services.constants import LEGAL_DISCLAIMER

env = Environment(loader=PackageLoader("app", "templates"), autoescape=select_autoescape())


def _provenance(review_status: str) -> str:
    return {"unreviewed": "AI", "approved": "AI✓", "edited": "AI✎", "rejected": "REJECTED"}[review_status]


def _mmss(ms: int | None) -> str:
    if ms is None:
        return "-"
    s = int(ms // 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


def build_snapshot(db, case: Case, includes_chat: bool) -> dict:
    videos = db.execute(select(Video).where(Video.case_id == case.id, Video.upload_complete)).scalars().all()
    persons = db.execute(select(Person).where(Person.case_id == case.id).order_by(Person.label)).scalars().all()
    events = db.execute(
        select(TimelineEvent).where(TimelineEvent.case_id == case.id).order_by(TimelineEvent.start_ms)
    ).scalars().all()
    label_by_id = {p.id: p.label for p in persons}
    refs = db.execute(select(SuspectReference).where(SuspectReference.case_id == case.id)).scalars().all()
    matches = []
    for ref in refs:
        for r in db.execute(
            select(SuspectMatchResult).where(SuspectMatchResult.suspect_reference_id == ref.id)
        ).scalars():
            matches.append({
                "reference_name": ref.display_name,
                "person_label": label_by_id.get(r.person_id),
                "cosine_similarity": r.cosine_similarity,
                "verdict": r.verdict,
                "review_status": r.review_status,
                "best_frame_ms": r.best_frame_ms,
            })
    chat = []
    if includes_chat:
        chat = [
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in db.execute(
                select(ChatMessage).where(ChatMessage.case_id == case.id).order_by(ChatMessage.created_at)
            ).scalars()
        ]
    review_log = [
        {"event_id": str(e.id), "review_status": e.review_status,
         "reviewed_by": str(e.reviewed_by) if e.reviewed_by else None, "human_note": e.human_note}
        for e in events if e.review_status != "unreviewed"
    ]
    return {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "case": {
            "id": str(case.id), "case_number": case.case_number, "title": case.title,
            "context_description": case.context_description,
            "counts": {
                "total": case.person_count_total, "male": case.person_count_male,
                "female": case.person_count_female, "unknown": case.person_count_unknown_gender,
            },
        },
        "media": [
            {"filename": v.original_filename, "sha256": v.sha256, "media_type": v.media_type,
             "duration_seconds": v.duration_seconds, "quality_notes": v.quality_notes or []}
            for v in videos
        ],
        "narrative": case.narrative_json,
        "persons": [
            {"label": p.label, "display_alias": p.display_alias,
             "gender_estimate": p.gender_estimate, "gender_confidence": p.gender_confidence,
             "gender_human_override": p.gender_human_override,
             "face_visible": p.face_visible, "appearance": p.appearance_description,
             "presence_intervals": p.presence_intervals, "activity_summary": p.activity_summary,
             "first_seen": _mmss(p.first_seen_ms), "last_seen": _mmss(p.last_seen_ms)}
            for p in persons
        ],
        "events": [
            {"id": str(e.id), "type": e.event_type, "label": e.label,
             "start": _mmss(e.start_ms), "end": _mmss(e.end_ms),
             "person": label_by_id.get(e.person_id), "target": label_by_id.get(e.target_person_id),
             "description": e.description, "confidence": e.confidence,
             "object_class": e.object_class, "is_suspicious": e.is_suspicious,
             "requires_human_review": e.requires_human_review,
             "review_status": e.review_status, "human_note": e.human_note,
             "provenance": _provenance(e.review_status)}
            for e in events
        ],
        "suspect_matches": matches,
        "chat": chat,
        "review_log": review_log,
        "disclaimer": LEGAL_DISCLAIMER,
    }


def build_export(export_id: str) -> None:
    with SessionLocal() as db:
        export = db.get(ExportReport, export_id)
        if export is None:
            return
        case = db.get(Case, export.case_id)
        user = db.get(User, export.generated_by)
        try:
            snapshot = build_snapshot(db, case, export.includes_chat)
            export.snapshot = snapshot
            html = env.get_template("report.html").render(
                s=snapshot, generated_by=user.full_name if user else "unknown",
                generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            )
            pdf_bytes = _render_pdf(html)
            sha = hashlib.sha256(pdf_bytes).hexdigest()
            # sha printed inside the footer: re-render once with the hash embedded
            html = env.get_template("report.html").render(
                s=snapshot, generated_by=user.full_name if user else "unknown",
                generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                content_sha256=sha,
            )
            pdf_bytes = _render_pdf(html)
            key = f"cases/{case.id}/exports/{export.id}.pdf"
            storage.upload_bytes(pdf_bytes, key, "application/pdf")
            export.s3_key_pdf = key
            export.sha256 = hashlib.sha256(pdf_bytes).hexdigest()
            export.status = "complete"
            audit.log(db, action="export.generated", actor_type="system", case_id=case.id,
                      entity_type="export_report", entity_id=export.id,
                      detail={"sha256": export.sha256, "content_sha256": sha})
        except Exception as exc:
            export.status = "failed"
            audit.log(db, action="export.generated", actor_type="system", case_id=case.id,
                      entity_type="export_report", entity_id=export.id,
                      detail={"error": str(exc)[:300]})
            raise
        finally:
            db.commit()


def _render_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf()
