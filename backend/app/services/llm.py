"""Anthropic API wrapper. LLM_FAKE=1 routes to a deterministic canned responder so the
full pipeline and tests run without network access or an API key."""
import hashlib
import json

from app.core.config import settings


def prompt_sha256(system: str, user: str) -> str:
    return hashlib.sha256((system + "\x00" + user).encode()).hexdigest()


def complete(system: str, user_blocks: list[str], model: str, max_tokens: int, temperature: float) -> str:
    if settings.llm_fake:
        return _fake_complete(system, user_blocks)
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": "\n\n".join(user_blocks)}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def rough_token_count(text: str) -> int:
    # 1 token ≈ 4 chars is sufficient for the budget policy; exact counting not required.
    return max(1, len(text) // 4)


def _fake_complete(system: str, user_blocks: list[str]) -> str:
    """Deterministic outputs keyed on the prompt kind, for CI and offline demos."""
    joined = "\n".join(user_blocks)
    if "<output_schema>" in joined:  # narrative request
        timeline = _extract_block(joined, "timeline")
        hypothesis = _extract_tag_text(joined, "case_context_hypothesis")
        return json.dumps(_fake_narrative(timeline, hypothesis))
    if "<earlier_conversation_summary>" in joined or "Answer the investigator" in system:
        timeline = _extract_block(joined, "timeline")
        events = (timeline or {}).get("events", [])
        if events:
            e = events[0]
            return (
                f"Based on the evidence timeline, the earliest recorded activity is "
                f"'{e['label']}' at {_mmss(e['start_ms'])} "
                f"[e:{e['event_id']}, conf {e['confidence']:.2f}]. "
                "This answer is limited to what the footage shows; it is not determinable "
                "from the evidence beyond the cited events."
            )
        return "This is not determinable from the evidence available in this case."
    if "Summarize this investigator" in system or "Summarize" in joined[:200]:
        return "Summary of earlier conversation: the investigator asked about timeline events; answers cited the recorded event ids."
    return "This is not determinable from the evidence available in this case."


def _extract_block(text: str, tag: str) -> dict | None:
    start, end = f"<{tag}>", f"</{tag}>"
    if start not in text or end not in text:
        return None
    raw = text.split(start, 1)[1].split(end, 1)[0].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _extract_tag_text(text: str, tag: str) -> str:
    start, end = f"<{tag}>", f"</{tag}>"
    if start not in text or end not in text:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def _mmss(ms: int) -> str:
    s = int(ms // 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


def _fake_hypothesis_check(hypothesis: str, persons: list, events: list) -> dict:
    """Deterministic hypothesis-vs-evidence pass (used when LLM_FAKE=1). Splits the
    context into sentence-claims and judges each against the timeline by keyword —
    a weak-but-honest stand-in for the real LLM's reasoning. Never asserts truth,
    only how the evidence relates to the claim."""
    import re

    labels = [p["label"] for p in persons]
    weapon_events = [e for e in events if e.get("object_class") in ("knife", "pistol", "rifle",
                                                                    "scissors", "baseball bat")]
    contact_events = [e for e in events if e.get("event_type") == "interaction"]
    claims = []
    for raw in re.split(r"(?<=[.!?])\s+", hypothesis.strip()):
        raw = raw.strip()
        if not raw:
            continue
        low = raw.lower()
        cited: list[str] = []
        if any(w in low for w in ("weapon", "knife", "gun", "pistol", "rifle", "armed")):
            if weapon_events:
                cited = [weapon_events[0]["event_id"]]
                verdict, why = "partially_supported", (
                    "The footage contains a possible object detection consistent with this, "
                    "but at low confidence — human review required; not identification.")
            else:
                verdict, why = "unsupported", "No object consistent with a weapon was detected in the footage."
        elif any(w in low for w in ("attack", "assault", "hit", "struck", "fought", "push")):
            if contact_events:
                cited = [contact_events[0]["event_id"]]
                verdict, why = "partially_supported", (
                    "The footage shows physical contact between persons, but does not establish "
                    "who initiated it or intent — human review required.")
            else:
                verdict, why = "unsupported", "No physical interaction between persons was detected."
        elif re.search(r"\b(two|three|four|\d+)\b.*(men|women|people|persons?)", low):
            verdict, why = ("supported" if len(labels) >= 2 else "contradicted",
                            f"The footage detected {len(labels)} distinct person(s): {', '.join(labels) or 'none'}.")
        else:
            verdict, why = "unsupported", (
                "The footage contains no specific evidence for or against this claim.")
        claims.append({"claim": raw, "verdict": verdict, "explanation": why,
                       "cited_event_ids": cited})
    supported = sum(1 for c in claims if c["verdict"] in ("supported", "partially_supported"))
    return {
        "hypothesis_text": hypothesis,
        "claims": claims,
        "overall": (f"{supported} of {len(claims)} claim(s) in the investigator's account have "
                    "some supporting evidence in the footage; the rest are unsupported or "
                    "contradicted. All findings require human verification.") if claims else
                   "No hypothesis text was provided to check.",
    }


def _fake_narrative(timeline: dict | None, hypothesis: str = "") -> dict:
    timeline = timeline or {"persons": [], "events": [], "videos": []}
    persons = timeline.get("persons", [])
    events = [e for e in timeline.get("events", []) if e.get("confidence", 0) >= 0.40]
    sections = []
    if events:
        cited = [e["event_id"] for e in events]
        text_parts = []
        for e in events:
            marker = " This event requires human review." if e.get("requires_human_review") else ""
            text_parts.append(
                f"At {_mmss(e['start_ms'])} the footage shows {e.get('description') or e['label']} "
                f"[e:{e['event_id']}, conf {e['confidence']:.2f}].{marker}"
            )
        sections.append({
            "section_index": 0,
            "time_range_ms": [events[0]["start_ms"], events[-1]["end_ms"]],
            "heading": "Recorded activity",
            "text": " ".join(text_parts),
            "cited_event_ids": cited,
        })
    person_summaries = []
    for p in persons:
        p_events = [e for e in events if e.get("person_label") == p["label"]]
        if p_events:
            txt = " ".join(
                f"At {_mmss(e['start_ms'])}: {e.get('description') or e['label']} "
                f"[e:{e['event_id']}, conf {e['confidence']:.2f}]."
                for e in p_events
            )
        else:
            txt = f"Person {p['label']} is present but no discrete events met the evidentiary threshold."
        person_summaries.append({
            "person_label": p["label"],
            "text": txt,
            "cited_event_ids": [e["event_id"] for e in p_events],
        })
    suspicious = [
        {
            "text": f"At {_mmss(e['start_ms'])}: {e.get('description') or e['label']} "
                    f"[e:{e['event_id']}, conf {e['confidence']:.2f}]. Requires human review.",
            "severity": "high" if e.get("object_class") in ("knife", "pistol", "rifle") else "medium",
            "cited_event_ids": [e["event_id"]],
            "requires_human_review": True,
        }
        for e in events if e.get("is_suspicious")
    ]
    uncertainties = [
        {
            "text": f"The event at {_mmss(e['start_ms'])} is uncertain "
                    f"({e.get('description') or e['label']}); the footage does not conclusively "
                    "establish what occurred and it requires human review.",
            "related_event_ids": [e["event_id"]],
        }
        for e in events if e.get("requires_human_review")
    ]
    for e in events:
        if e.get("event_type") == "interaction" and not e.get("actor_direction"):
            uncertainties.append({
                "text": f"The footage does not establish who initiated the contact at {_mmss(e['start_ms'])}.",
                "related_event_ids": [e["event_id"]],
            })
    return {
        "schema_version": "1.0",
        "overall_summary": (
            f"The footage contains {len(persons)} detected person(s) and {len(events)} recorded event(s). "
            "All statements below are limited to what the evidence timeline shows."
            if persons else
            "No persons were detected in the analyzed footage; the narrative is limited to scene-level observations."
        ),
        "narrative_sections": sections,
        "person_summaries": person_summaries,
        "suspicious_activity_summary": suspicious,
        "uncertainties": uncertainties,
        "evidence_gaps": [n for v in timeline.get("videos", []) for n in v.get("quality_notes", [])],
        "hypothesis_check": _fake_hypothesis_check(hypothesis, persons, events),
        "disclaimer": "",
    }
