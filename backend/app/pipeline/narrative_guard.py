"""Deterministic post-validation of LLM narrative output (Stage 3, steps 1-5).

The model's output is never trusted: citations are verified against the timeline,
sub-threshold citations rejected, forbidden assertive phrases without qualifying
evidence replaced, and the legal disclaimer injected in code.
"""
import re
from dataclasses import dataclass, field

from app.schemas.narrative import NarrativeDoc
from app.schemas.timeline import CaseTimeline
from app.services.constants import LEGAL_DISCLAIMER

CITATION_RE = re.compile(r"\[e:([0-9a-fA-F-]+),\s*conf\s*([0-9.]+)\]")
FORBIDDEN_ASSERTIVE = ("attacked", "assaulted", "stole", "intended", "guilty", "murdered", "robbed")
UNCERTAINTY_SENTENCE = "The footage does not conclusively establish this; human review required."
MIN_CITABLE_CONF = 0.40
ATTACK_MIN_CONF = 0.60


@dataclass
class GuardReport:
    stripped_sentences: list[str] = field(default_factory=list)
    replaced_sentences: list[str] = field(default_factory=list)
    ok: bool = True


def _split_sentences(text: str) -> list[str]:
    # Split on sentence enders not inside citation brackets.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", text.strip())
    return [p for p in parts if p]


def _event_index(timeline: CaseTimeline) -> dict:
    index = {}
    for e in timeline.events:
        index[e.event_id] = e
        index[e.event_id[:8]] = e  # short-id citations allowed
    return index


def _citation_events(sentence: str, events_by_id: dict) -> list | None:
    """Events cited in a sentence; None if any citation is unknown."""
    cited = []
    for m in CITATION_RE.finditer(sentence):
        e = events_by_id.get(m.group(1)) or events_by_id.get(m.group(1)[:8])
        if e is None:
            return None
        cited.append(e)
    return cited


def _attack_claim_allowed(events: list) -> bool:
    """Rule 4: interaction + both persons + contact/struggle + resolved direction + conf >= 0.60."""
    return any(
        e.event_type == "interaction"
        and e.label in ("physical_contact", "struggle")
        and e.person_label and e.target_person_label
        and e.actor_direction
        and e.confidence >= ATTACK_MIN_CONF
        for e in events
    )


def _guard_text(text: str, events_by_id: dict, report: GuardReport) -> str:
    kept: list[str] = []
    for sentence in _split_sentences(text):
        cited = _citation_events(sentence, events_by_id)
        if cited is None:  # unknown citation → strip sentence entirely
            report.stripped_sentences.append(sentence)
            continue
        if any(e.confidence < MIN_CITABLE_CONF for e in cited):
            report.stripped_sentences.append(sentence)
            continue
        lower = sentence.lower()
        if any(word in lower for word in FORBIDDEN_ASSERTIVE):
            if not cited or not _attack_claim_allowed(cited):
                report.replaced_sentences.append(sentence)
                kept.append(UNCERTAINTY_SENTENCE)
                continue
        kept.append(sentence)
    return " ".join(kept)


def guard_narrative(doc: NarrativeDoc, timeline: CaseTimeline) -> tuple[NarrativeDoc, GuardReport]:
    report = GuardReport()
    events_by_id = _event_index(timeline)
    person_labels = {p.label for p in timeline.persons}

    for section in doc.narrative_sections:
        section.text = _guard_text(section.text, events_by_id, report)
        section.cited_event_ids = [
            i for i in section.cited_event_ids if i in events_by_id or i[:8] in events_by_id
        ]
    doc.person_summaries = [s for s in doc.person_summaries if s.person_label in person_labels]
    for s in doc.person_summaries:
        s.text = _guard_text(s.text, events_by_id, report)
    for s in doc.suspicious_activity_summary:
        s.text = _guard_text(s.text, events_by_id, report)
        s.requires_human_review = True
    doc.overall_summary = doc.overall_summary.strip()

    # Hypothesis check: drop any citation that doesn't resolve to a real event, and
    # never let a claim be marked 'supported'/'contradicted' with zero backing events —
    # downgrade those to 'unsupported' so the UI can't imply evidence that isn't there.
    if doc.hypothesis_check is not None:
        for claim in doc.hypothesis_check.claims:
            claim.cited_event_ids = [
                i for i in claim.cited_event_ids if i in events_by_id or i[:8] in events_by_id
            ]
            if claim.verdict in ("supported", "contradicted", "partially_supported") \
                    and not claim.cited_event_ids:
                claim.verdict = "unsupported"

    doc.disclaimer = LEGAL_DISCLAIMER  # injected in code, never trusted from the model
    report.ok = True
    return doc, report


def extract_citations(text: str, events_by_id: dict) -> list[dict]:
    out = []
    for m in CITATION_RE.finditer(text):
        e = events_by_id.get(m.group(1)) or events_by_id.get(m.group(1)[:8])
        if e is not None:
            out.append({
                "event_id": e.event_id,
                "start_ms": e.start_ms,
                "end_ms": e.end_ms,
                "confidence": e.confidence,
            })
    return out
