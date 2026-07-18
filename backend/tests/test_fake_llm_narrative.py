"""Phase 4 done-criteria against the fixture: the (fake) LLM narrative validates,
every citation resolves, the unclear-direction interaction is flagged uncertain,
the 0.47 weapon is review-flagged, and the disclaimer is injected."""
import json

from app.pipeline.narrative_guard import CITATION_RE, guard_narrative
from app.schemas.narrative import NarrativeDoc
from app.schemas.timeline import CaseTimeline
from app.services import llm
from app.services.constants import LEGAL_DISCLAIMER


def test_fake_narrative_end_to_end(fixture_timeline_dict):
    timeline = CaseTimeline.model_validate(fixture_timeline_dict)
    raw = llm.complete(
        system="narrative",
        user_blocks=[
            f"<timeline>\n{json.dumps(fixture_timeline_dict)}\n</timeline>",
            "<output_schema>\n{}\n</output_schema>",
        ],
        model="claude-fable-5", max_tokens=8000, temperature=0.2,
    )
    doc = NarrativeDoc.model_validate_json(raw)
    guarded, report = guard_narrative(doc, timeline)

    assert guarded.disclaimer == LEGAL_DISCLAIMER
    event_ids = {e.event_id for e in timeline.events} | {e.event_id[:8] for e in timeline.events}
    all_text = " ".join(s.text for s in guarded.narrative_sections)
    citations = CITATION_RE.findall(all_text)
    assert citations, "narrative must contain citations"
    assert all(cid in event_ids or cid[:8] in event_ids for cid, _ in citations)
    # unclear-direction interaction described as unestablished
    assert any("does not establish who initiated" in u.text for u in guarded.uncertainties)
    # the conf-0.47 weapon appears with the review flag
    weapon = next(e for e in timeline.events if e.object_class == "knife")
    assert weapon.requires_human_review
    assert any(weapon.event_id in s.cited_event_ids for s in guarded.suspicious_activity_summary)
    # person summaries cover every fixture person, incl. face-not-visible C
    assert {s.person_label for s in guarded.person_summaries} == {"A", "B", "C"}
