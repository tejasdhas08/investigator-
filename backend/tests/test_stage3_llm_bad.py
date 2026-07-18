"""Canned bad-LLM-response fixtures (Phase 4 test data): invalid JSON, fake citation,
uncited 'attacked' — each must be neutralized by parsing/guard, never surfaced."""
import json
import pathlib

import pytest
from pydantic import ValidationError

from app.pipeline.narrative_guard import UNCERTAINTY_SENTENCE, guard_narrative
from app.schemas.narrative import NarrativeDoc
from app.schemas.timeline import CaseTimeline

BAD_DIR = pathlib.Path(__file__).parent / "fixtures" / "llm_bad"


def test_invalid_json_rejected():
    raw = (BAD_DIR / "invalid_json.txt").read_text()
    with pytest.raises((ValidationError, ValueError)):
        NarrativeDoc.model_validate_json(raw)


def test_fake_citation_neutralized(fixture_timeline_dict):
    t = CaseTimeline.model_validate(fixture_timeline_dict)
    doc = NarrativeDoc.model_validate_json((BAD_DIR / "fake_citation.json").read_text())
    guarded, report = guard_narrative(doc, t)
    assert "left the country" not in guarded.narrative_sections[0].text
    assert report.stripped_sentences


def test_uncited_attack_neutralized(fixture_timeline_dict):
    t = CaseTimeline.model_validate(fixture_timeline_dict)
    doc = NarrativeDoc.model_validate_json((BAD_DIR / "uncited_attack.json").read_text())
    guarded, report = guard_narrative(doc, t)
    assert UNCERTAINTY_SENTENCE in guarded.narrative_sections[0].text
    assert report.replaced_sentences
