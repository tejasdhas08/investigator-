"""Stage 4 budget policy: compression levels behave exactly as specified."""
from app.services.chat_context import compress_timeline, effective_narrative


def test_level1_drops_evidence_keys_and_low_conf(fixture_timeline_dict):
    t = compress_timeline(fixture_timeline_dict, 1)
    assert all("evidence_frame_s3_keys" not in e for e in t["events"])
    assert all(e["confidence"] >= 0.40 for e in t["events"])


def test_level2_merges_action_runs(fixture_timeline_dict):
    events = fixture_timeline_dict["events"]
    # duplicate a walking event to create a mergeable run
    import copy

    dup = copy.deepcopy(next(e for e in events if e["label"] == "walking"))
    dup["start_ms"] = dup["end_ms"]
    dup["end_ms"] = dup["end_ms"] + 5000
    events.append(dup)
    before = len(compress_timeline(fixture_timeline_dict, 1)["events"])
    after = len(compress_timeline(fixture_timeline_dict, 2)["events"])
    assert after == before - 1


def test_level3_never_drops_suspicious_or_interactions(fixture_timeline_dict):
    t3 = compress_timeline(fixture_timeline_dict, 3)
    kept_types = {e["event_type"] for e in t3["events"]}
    assert "interaction" in kept_types
    assert any(e["is_suspicious"] for e in t3["events"])
    assert all(
        e["is_suspicious"] or e["event_type"] == "interaction" or e["confidence"] >= 0.50
        for e in t3["events"]
    )


def test_effective_narrative_applies_human_edits():
    doc = {
        "narrative_sections": [{"text": "AI text", "heading": "h"}],
        "human_edits": [{"path": "narrative_sections[0].text", "original_text": "AI text",
                         "edited_text": "Human corrected text", "edited_by": "u", "edited_at": "t"}],
    }
    out = effective_narrative(doc)
    assert out["narrative_sections"][0]["text"] == "Human corrected text"
    assert doc["narrative_sections"][0]["text"] == "AI text"  # original untouched
