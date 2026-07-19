"""Phase 3 hypothesis-vs-evidence check: claims are judged against the timeline,
citations are validated by the guard, and unsupported claims never carry evidence."""
import json

from app.pipeline.narrative_guard import guard_narrative
from app.schemas.narrative import NarrativeDoc
from app.schemas.timeline import CaseTimeline
from app.services import llm


def _narrative_for(timeline_dict, hypothesis):
    raw = llm.complete(
        system="narrative",
        user_blocks=[
            f"<case_context_hypothesis>\n{hypothesis}\n</case_context_hypothesis>",
            f"<timeline>\n{json.dumps(timeline_dict)}\n</timeline>",
            "<output_schema>\n{}\n</output_schema>",
        ],
        model="x", max_tokens=8000, temperature=0.2,
    )
    return NarrativeDoc.model_validate_json(raw)


def test_hypothesis_check_present_and_cited(fixture_timeline_dict):
    timeline = CaseTimeline.model_validate(fixture_timeline_dict)
    doc = _narrative_for(fixture_timeline_dict,
                         "I believe Person A attacked Person B with a weapon. Two people were present.")
    doc, _ = guard_narrative(doc, timeline)
    hc = doc.hypothesis_check
    assert hc is not None and hc.claims
    verdicts = {c.verdict for c in hc.claims}
    assert verdicts <= {"supported", "contradicted", "partially_supported", "unsupported"}
    # the weapon + attack claims should find the fixture's low-conf weapon / interaction
    assert any("weapon" in c.claim.lower() and c.cited_event_ids for c in hc.claims)
    # every cited id must be a real event id
    event_ids = {e.event_id for e in timeline.events} | {e.event_id[:8] for e in timeline.events}
    for c in hc.claims:
        for cid in c.cited_event_ids:
            assert cid in event_ids or cid[:8] in event_ids


def test_supported_verdict_without_citation_is_downgraded(fixture_timeline_dict):
    timeline = CaseTimeline.model_validate(fixture_timeline_dict)
    doc = _narrative_for(fixture_timeline_dict, "Something happened.")
    # inject a bogus 'supported' claim with a fake citation
    doc.hypothesis_check.claims.append(
        type(doc.hypothesis_check.claims[0])(
            claim="A UFO landed.", verdict="supported",
            explanation="fabricated", cited_event_ids=["00000000-dead"]),
    )
    doc, _ = guard_narrative(doc, timeline)
    ufo = next(c for c in doc.hypothesis_check.claims if "UFO" in c.claim)
    assert ufo.verdict == "unsupported"  # fake citation stripped -> downgraded
    assert ufo.cited_event_ids == []
