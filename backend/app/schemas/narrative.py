"""Narrative JSON schema (ARCHITECTURE.md Section 3.11) — Stage 3 output."""
from typing import Literal

from pydantic import BaseModel, Field


class NarrativeSection(BaseModel):
    section_index: int
    time_range_ms: tuple[int, int]
    heading: str
    text: str
    cited_event_ids: list[str]


class PersonSummary(BaseModel):
    person_label: str
    text: str
    cited_event_ids: list[str]


class SuspiciousSummary(BaseModel):
    text: str
    severity: Literal["low", "medium", "high"]
    cited_event_ids: list[str]
    requires_human_review: bool = True


class Uncertainty(BaseModel):
    text: str
    related_event_ids: list[str] = []


class HypothesisClaim(BaseModel):
    """One checkable assertion extracted from the investigator's context, judged against
    the timeline (Phase 3 flagship feature). verdict is never 'confirmed as fact' —
    only how the *evidence* relates to the claim."""
    claim: str
    verdict: Literal["supported", "contradicted", "unsupported", "partially_supported"]
    explanation: str
    cited_event_ids: list[str] = []


class HypothesisCheck(BaseModel):
    hypothesis_text: str
    claims: list[HypothesisClaim] = []
    overall: str = ""


class HumanEdit(BaseModel):
    path: str
    original_text: str
    edited_text: str
    edited_by: str
    edited_at: str


class NarrativeDoc(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    model: str = ""
    generated_at: str = ""
    overall_summary: str
    narrative_sections: list[NarrativeSection]
    person_summaries: list[PersonSummary]
    suspicious_activity_summary: list[SuspiciousSummary] = []
    uncertainties: list[Uncertainty] = []
    evidence_gaps: list[str] = []
    hypothesis_check: HypothesisCheck | None = None
    disclaimer: str = ""
    human_edits: list[HumanEdit] = []

    model_config = {"protected_namespaces": ()}
