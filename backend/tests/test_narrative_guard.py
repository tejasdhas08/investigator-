"""Phase 4 done-criteria: the guard strips fake citations, strips sub-threshold
citations, replaces uncited 'attacked'-class claims, and always injects the disclaimer."""
from app.pipeline.narrative_guard import (
    UNCERTAINTY_SENTENCE, guard_narrative,
)
from app.schemas.narrative import NarrativeDoc, PersonSummary
from app.schemas.timeline import CaseTimeline
from app.services.constants import LEGAL_DISCLAIMER


def _doc(sections_text: str, cited=None) -> NarrativeDoc:
    return NarrativeDoc(
        overall_summary="Summary.",
        narrative_sections=[{
            "section_index": 0, "time_range_ms": [0, 1000],
            "heading": "H", "text": sections_text, "cited_event_ids": cited or [],
        }],
        person_summaries=[],
    )


def _timeline(fixture_timeline_dict) -> CaseTimeline:
    return CaseTimeline.model_validate(fixture_timeline_dict)


def test_fake_citation_stripped(fixture_timeline_dict):
    t = _timeline(fixture_timeline_dict)
    real = t.events[0].event_id
    doc = _doc(
        f"Person A enters at 00:03 [e:{real}, conf 0.87]. "
        "Person A then flew away [e:00000000-dead-beef-0000-000000000000, conf 0.99]."
    )
    guarded, report = guard_narrative(doc, t)
    assert "flew away" not in guarded.narrative_sections[0].text
    assert "enters at 00:03" in guarded.narrative_sections[0].text
    assert len(report.stripped_sentences) == 1


def test_subthreshold_citation_stripped(fixture_timeline_dict):
    for e in fixture_timeline_dict["events"]:
        e["confidence"] = 0.30
    t = _timeline(fixture_timeline_dict)
    eid = t.events[0].event_id
    doc = _doc(f"Person A enters at 00:03 [e:{eid}, conf 0.30].")
    guarded, report = guard_narrative(doc, t)
    assert guarded.narrative_sections[0].text == ""
    assert len(report.stripped_sentences) == 1


def test_uncited_attack_claim_replaced(fixture_timeline_dict):
    t = _timeline(fixture_timeline_dict)
    doc = _doc("Person A attacked Person B without mercy.")
    guarded, report = guard_narrative(doc, t)
    assert guarded.narrative_sections[0].text == UNCERTAINTY_SENTENCE
    assert len(report.replaced_sentences) == 1


def test_attack_claim_with_unclear_direction_replaced(fixture_timeline_dict):
    t = _timeline(fixture_timeline_dict)
    interaction = next(e for e in t.events if e.event_type == "interaction")
    assert interaction.actor_direction is None  # fixture's unclear-direction contact
    doc = _doc(f"Person A attacked Person B [e:{interaction.event_id}, conf 0.64].")
    guarded, _ = guard_narrative(doc, t)
    assert guarded.narrative_sections[0].text == UNCERTAINTY_SENTENCE


def test_attack_claim_with_resolved_direction_kept(fixture_timeline_dict):
    for e in fixture_timeline_dict["events"]:
        if e["event_type"] == "interaction":
            e["actor_direction"] = "person->target"
            e["confidence"] = 0.68
    t = _timeline(fixture_timeline_dict)
    interaction = next(e for e in t.events if e.event_type == "interaction")
    text = (f"The footage shows Person A making contact with Person B, consistent with a "
            f"strike, which some would say means A attacked B "
            f"[e:{interaction.event_id}, conf 0.68].")
    guarded, report = guard_narrative(_doc(text), t)
    assert "consistent with a strike" in guarded.narrative_sections[0].text
    assert not report.replaced_sentences


def test_disclaimer_always_injected(fixture_timeline_dict):
    t = _timeline(fixture_timeline_dict)
    doc = _doc("Nothing notable occurred here.")
    doc.disclaimer = "model-provided disclaimer that must be overwritten"
    guarded, _ = guard_narrative(doc, t)
    assert guarded.disclaimer == LEGAL_DISCLAIMER


def test_unknown_person_summary_dropped(fixture_timeline_dict):
    t = _timeline(fixture_timeline_dict)
    doc = _doc("Ok.")
    doc.person_summaries = [
        PersonSummary(person_label="A", text="Present.", cited_event_ids=[]),
        PersonSummary(person_label="Q", text="Hallucinated person.", cited_event_ids=[]),
    ]
    guarded, _ = guard_narrative(doc, t)
    assert [s.person_label for s in guarded.person_summaries] == ["A"]
