"""Stage 4 context assembly and context-length budget policy (ARCHITECTURE.md Stage 4).

Priority when over the 160k-token input budget:
1. system + narrative + question are always kept;
2. timeline is progressively compressed (drop evidence keys → merge action runs →
   drop conf<0.50 non-suspicious events; suspicious/interaction events are never dropped);
3. chat history: last 10 messages verbatim, older messages replaced by a rolling
   summary regenerated every 10 messages with the cheap summary model.
"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat import ChatMessage, ChatSummary
from app.services import llm

INPUT_BUDGET_TOKENS = 160_000
VERBATIM_TAIL = 10
SUMMARY_EVERY = 10


def compress_timeline(timeline: dict, level: int) -> dict:
    """Deterministic compression, lossless w.r.t. what the model may cite at level<=1.
    level 0: as-is; 1: drop evidence frame keys + no_match suspect entries + conf<0.40 events;
    2: also merge consecutive identical action runs per person; 3: also drop conf<0.50
    non-suspicious, non-interaction events."""
    t = json.loads(json.dumps(timeline))
    if level >= 1:
        for p in t.get("persons", []):
            sm = p.get("suspect_match")
            if sm and sm.get("verdict") == "no_match":
                p["suspect_match"] = None
        t["events"] = [e for e in t.get("events", []) if e.get("confidence", 0) >= 0.40]
        for e in t["events"]:
            e.pop("evidence_frame_s3_keys", None)
            e.pop("bbox", None)
    if level >= 2:
        merged, prev = [], None
        for e in sorted(t["events"], key=lambda x: (x.get("person_label") or "", x["start_ms"])):
            if (
                prev is not None
                and e["event_type"] == "action" and prev["event_type"] == "action"
                and e.get("person_label") == prev.get("person_label")
                and e["label"] == prev["label"]
            ):
                prev["end_ms"] = max(prev["end_ms"], e["end_ms"])
                prev["end_frame"] = max(prev["end_frame"], e["end_frame"])
                prev["confidence"] = min(prev["confidence"], e["confidence"])
            else:
                merged.append(e)
                prev = e
        t["events"] = sorted(merged, key=lambda x: x["start_ms"])
    if level >= 3:
        t["events"] = [
            e for e in t["events"]
            if e.get("is_suspicious") or e["event_type"] == "interaction" or e.get("confidence", 0) >= 0.50
        ]
    return t


def _history_blocks(db: Session, case_id, history: list[ChatMessage]) -> list[str]:
    if len(history) <= VERBATIM_TAIL:
        return [f"{m.role.upper()}: {m.content}" for m in history]
    tail = history[-VERBATIM_TAIL:]
    boundary = history[-(VERBATIM_TAIL + 1)]
    summary = db.execute(
        select(ChatSummary)
        .where(ChatSummary.case_id == case_id)
        .order_by(ChatSummary.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    needs_new = summary is None or (
        len(history) - VERBATIM_TAIL
    ) - _summary_covers(history, summary) >= SUMMARY_EVERY
    if needs_new:
        older = history[:-VERBATIM_TAIL]
        text = "\n".join(f"{m.role}: {m.content}" for m in older)
        summarized = llm.complete(
            system="Summarize this investigator Q&A exchange in <=300 words, preserving every cited event id.",
            user_blocks=[text],
            model=settings.summary_model,
            max_tokens=600,
            temperature=0.0,
        )
        summary = ChatSummary(case_id=case_id, up_to_message_id=boundary.id, summary=summarized)
        db.add(summary)
        db.flush()
    blocks = [f"<earlier_conversation_summary>\n{summary.summary}\n</earlier_conversation_summary>"]
    blocks += [f"{m.role.upper()}: {m.content}" for m in tail]
    return blocks


def _summary_covers(history: list[ChatMessage], summary: ChatSummary) -> int:
    for i, m in enumerate(history):
        if m.id == summary.up_to_message_id:
            return i + 1
    return 0


def assemble(db: Session, case, timeline: dict, question: str) -> tuple[list[str], int]:
    """Returns (user_blocks, compression_level_used)."""
    history = db.execute(
        select(ChatMessage).where(ChatMessage.case_id == case.id).order_by(ChatMessage.created_at)
    ).scalars().all()
    narrative_block = f"<narrative>\n{json.dumps(effective_narrative(case.narrative_json))}\n</narrative>"
    history_blocks = _history_blocks(db, case.id, history)
    question_block = f"QUESTION: {question}"

    level = 1
    while True:
        timeline_block = f"<timeline>\n{json.dumps(compress_timeline(timeline, level))}\n</timeline>"
        blocks = [narrative_block, timeline_block, *history_blocks, question_block]
        if llm.rough_token_count("\n".join(blocks)) <= INPUT_BUDGET_TOKENS or level >= 3:
            return blocks, level
        level += 1


def effective_narrative(narrative_json: dict | None) -> dict:
    """Narrative with human edits applied so the AI never re-asserts rejected/edited text."""
    if not narrative_json:
        return {}
    doc = json.loads(json.dumps(narrative_json))
    for edit in doc.get("human_edits", []):
        _apply_edit(doc, edit["path"], edit["edited_text"])
    return doc


def _apply_edit(doc: dict, path: str, new_text: str) -> None:
    import re

    parts = path.split(".")
    node = doc
    for part in parts[:-1]:
        m = re.fullmatch(r"(\w+)(?:\[(\d+)\])?", part)
        if not m or not isinstance(node, dict) or m.group(1) not in node:
            return
        node = node[m.group(1)]
        if m.group(2) is not None:
            if not isinstance(node, list) or int(m.group(2)) >= len(node):
                return
            node = node[int(m.group(2))]
    last = re.fullmatch(r"(\w+)(?:\[(\d+)\])?", parts[-1])
    if last and isinstance(node, dict) and last.group(1) in node:
        if last.group(2) is None:
            node[last.group(1)] = new_text
