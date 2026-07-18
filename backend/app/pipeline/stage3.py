"""Stage 3: narrative generation (the core feature).

Builds the Timeline JSON, calls the LLM with the fixed system prompt, then runs the
deterministic narrative guard. The model's output is validated, cited claims are
audit-logged, and the disclaimer is injected in code.
"""
import hashlib
import json
import pathlib
from datetime import datetime, timezone

from pydantic import ValidationError

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.case import Case
from app.models.person import Person
from app.pipeline.narrative_guard import guard_narrative
from app.schemas.narrative import NarrativeDoc
from app.schemas.timeline import CaseTimeline
from app.services import audit, chat_context, llm, progress, timeline_builder

SYSTEM_PROMPT = (pathlib.Path(__file__).resolve().parent.parent / "prompts" / "narrative.txt").read_text()
TIMELINE_TOKEN_BUDGET = 150_000


class LLMUnavailable(Exception):
    pass


def _user_message(case: Case, timeline_json: str, static_only: bool) -> str:
    schema = json.dumps(NarrativeDoc.model_json_schema())
    static_note = (
        "\nMEDIA IS STATIC PHOTOS: make no sequence claims within a photo.\n" if static_only else ""
    )
    review_notes = _human_review_notes(case)
    return (
        f"<case_context_hypothesis>\n{case.context_description}\n</case_context_hypothesis>\n\n"
        f"<timeline>\n{timeline_json}\n</timeline>\n\n"
        f"<output_schema>\n{schema}\n</output_schema>\n"
        f"{review_notes}{static_note}\n"
        "Write the complete narrative now. Cover: (a) chronological narrative_sections\n"
        "spanning the full footage; (b) one person_summary per person describing everything\n"
        "that person did; (c) suspicious_activity_summary; (d) uncertainties; (e)\n"
        "evidence_gaps. Timestamps in text as MM:SS."
    )


def _human_review_notes(case: Case) -> str:
    notes = []
    with SessionLocal() as db:
        from sqlalchemy import select

        from app.models.timeline_event import TimelineEvent

        for e in db.execute(
            select(TimelineEvent).where(TimelineEvent.case_id == case.id,
                                        TimelineEvent.human_note.isnot(None))
        ).scalars():
            notes.append(f"- event {e.id}: {e.human_note}")
    if not notes:
        return ""
    return "<human_review_notes>\n" + "\n".join(notes) + "\n</human_review_notes>\n"


def run(case_id: str) -> None:
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        case.status = "narrating"
        db.commit()
        progress.set_progress(case_id, "narrating", 10)

        timeline = timeline_builder.build_timeline(db, case, exclude_rejected=True)
        timeline_dict = timeline.model_dump()
        timeline_json = json.dumps(timeline_dict, separators=(",", ":"))
        if llm.rough_token_count(timeline_json) > TIMELINE_TOKEN_BUDGET:
            timeline_dict = chat_context.compress_timeline(timeline_dict, level=2)
            timeline_json = json.dumps(timeline_dict, separators=(",", ":"))

        static_only = all(v.media_type == "photo" for v in timeline.videos) and bool(timeline.videos)
        user_msg = _user_message(case, timeline_json, static_only)
        timeline_sha = hashlib.sha256(timeline_json.encode()).hexdigest()
        prompt_sha = llm.prompt_sha256(SYSTEM_PROMPT, user_msg)

        doc = _generate_validated(user_msg)
        progress.set_progress(case_id, "narrating", 70)

        doc, report = guard_narrative(doc, timeline)
        for sentence in report.stripped_sentences:
            audit.log(db, action="narrative_citation_stripped", actor_type="system",
                      case_id=case.id, detail={"sentence": sentence[:500]})
        for sentence in report.replaced_sentences:
            audit.log(db, action="narrative_claim_replaced", actor_type="system",
                      case_id=case.id, detail={"sentence": sentence[:500]})

        doc.model = settings.narrative_model
        doc.generated_at = datetime.now(timezone.utc).isoformat()
        case.narrative_json = doc.model_dump()
        case.narrative_model = settings.narrative_model
        case.narrative_generated_at = datetime.now(timezone.utc)

        for p_summary in doc.person_summaries:
            person = next(
                (p for p in db.query(Person).filter(Person.case_id == case.id)
                 if p.label == p_summary.person_label), None)
            if person is not None:
                person.activity_summary = p_summary.text

        _audit_claims(db, case, doc, timeline, prompt_sha, timeline_sha)
        audit.log(db, action="ai.narrative.generated", actor_type="ai", case_id=case.id,
                  detail={"model_id": settings.narrative_model, "prompt_sha256": prompt_sha,
                          "timeline_sha256": timeline_sha,
                          "sections": len(doc.narrative_sections)})
        case.status = "complete"
        db.commit()
        progress.set_progress(case_id, "narrating", 100)


def _generate_validated(user_msg: str) -> NarrativeDoc:
    last_error = None
    for attempt in range(2):
        msg = user_msg if attempt == 0 else (
            user_msg + f"\n\nYour previous output was invalid JSON for the schema: {last_error}. "
                       "Output ONLY corrected valid JSON."
        )
        try:
            raw = llm.complete(system=SYSTEM_PROMPT, user_blocks=[msg],
                               model=settings.narrative_model, max_tokens=8000, temperature=0.2)
        except Exception as exc:
            raise LLMUnavailable(str(exc)) from exc
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1].removeprefix("json").strip()
            return NarrativeDoc.model_validate_json(cleaned)
        except (ValidationError, ValueError) as exc:
            last_error = str(exc)[:500]
    raise RuntimeError(f"narrative_invalid_json: {last_error}")


def _audit_claims(db, case, doc: NarrativeDoc, timeline: CaseTimeline,
                  prompt_sha: str, timeline_sha: str) -> None:
    conf_by_event = {e.event_id: e.confidence for e in timeline.events}

    def claim(text: str, ctype: str, event_ids: list[str]):
        audit.ai_claim(
            db, case_id=case.id, claim_text=text[:1000], claim_type=ctype,
            cited_event_ids=event_ids,
            confidences=[conf_by_event.get(i, -1) for i in event_ids],
            model_id=settings.narrative_model,
            prompt_sha256=prompt_sha, timeline_sha256=timeline_sha,
        )

    for s in doc.narrative_sections:
        claim(s.text, "narrative_sentence", s.cited_event_ids)
    for s in doc.person_summaries:
        claim(s.text, "person_summary", s.cited_event_ids)
    for s in doc.suspicious_activity_summary:
        claim(s.text, "suspicious_summary", s.cited_event_ids)
