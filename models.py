"""Data contracts and traceability checks for the Word reporting component.

The evidence manifest is owned by the application. Never accept it from the
model as proof of its own citations. These checks do not validate clinical or
regulatory reasoning, extraction accuracy, or document applicability.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Citation(StrictModel):
    source_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=700)


class Finding(StrictModel):
    check_id: str = Field(min_length=1)
    # Readability targets are instructions, never character-limit rejection gates.
    record_element: str = Field(min_length=1, description="A short 2-5 word label for the review area.")
    what_was_done: str = Field(min_length=1, description="One sentence, usually 15-25 words, with only the observation needed for this check.")
    record_evidence: list[Citation]
    procedure_references: list[Citation]
    assessment: Literal[
        "done_properly", "needs_trainer_review", "potential_gap",
        "not_assessable", "not_applicable"
    ]
    feedback: str = Field(min_length=1, description="One or two sentences, usually 30-45 words: conclusion, essential qualification and next action. Do not repeat the observation or quote procedures. These are soft targets; longer explanations are allowed when essential.")
    priority: Literal["high", "medium", "low", "none"]
    study_action: str = Field(description="One action in 15-25 words, or empty when priority is none. Omit routine practice tasks for work already done properly.")


class Review(StrictModel):
    overall_summary: str = Field(min_length=1, description="A concise summary of actual coverage and limitations.")
    limitations: list[str]
    findings: list[Finding] = Field(min_length=1, max_length=60)


class Chunk(StrictModel):
    id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    text: str = Field(min_length=1)


class EvidenceSource(StrictModel):
    id: str = Field(min_length=1)
    kind: Literal["record", "procedure"]
    name: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    record_id: str | None
    revision: str | None
    approved_revision: bool
    file_sha256: str | None
    extracted_text_sha256: str
    chunks: list[Chunk] = Field(min_length=1)


class EvidenceManifest(StrictModel):
    mode: Literal["demo", "review"]
    review_id: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    record_stage: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    template_version: str = Field(min_length=1)
    policy_selection: str = Field(min_length=1)
    expected_check_ids: list[str] = Field(min_length=1)
    sources: list[EvidenceSource]
    limitations: list[str]


def extracted_digest(chunks: list[Chunk]) -> str:
    payload = json.dumps([c.model_dump() for c in chunks],
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _norm(value: str) -> str:
    return " ".join(value.split())


def validate_traceability(review: Review, evidence: EvidenceManifest) -> None:
    """Reject malformed or untraceable data before creating a Word report."""
    sources = {s.id: s for s in evidence.sources}
    if len(sources) != len(evidence.sources):
        raise ValueError("Duplicate evidence source IDs")
    expected = evidence.expected_check_ids
    actual = [f.check_id for f in review.findings]
    if len(set(expected)) != len(expected) or len(set(actual)) != len(actual):
        raise ValueError("Duplicate check IDs")
    if set(actual) != set(expected):
        raise ValueError("The review must cover every expected check exactly once")
    for source in evidence.sources:
        if len({c.id for c in source.chunks}) != len(source.chunks):
            raise ValueError(f"Duplicate chunk IDs in {source.id}")
        if extracted_digest(source.chunks) != source.extracted_text_sha256:
            raise ValueError(f"Extracted text digest mismatch for {source.id}")
        if source.kind == "record" and source.record_id != evidence.record_id:
            raise ValueError(f"Record ID mismatch for {source.id}")
        if source.kind == "procedure" and evidence.mode == "review":
            if not source.revision or not source.approved_revision:
                raise ValueError(f"Procedure revision is not approved: {source.id}")
        if evidence.mode == "review":
            h = source.file_sha256 or ""
            if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
                raise ValueError(f"Original file digest is required for {source.id}")

    def check_ref(ref: Citation, kind: str) -> None:
        source = sources.get(ref.source_id)
        if source is None or source.kind != kind:
            raise ValueError(f"Unknown source or wrong source type: {ref.source_id}")
        chunk = next((c for c in source.chunks if c.id == ref.chunk_id), None)
        if chunk is None or _norm(ref.quote) not in _norm(chunk.text):
            raise ValueError(f"Unverified excerpt: {ref.source_id}/{ref.chunk_id}")

    for finding in review.findings:
        for ref in finding.record_evidence:
            check_ref(ref, "record")
        for ref in finding.procedure_references:
            check_ref(ref, "procedure")
        if finding.assessment != "not_assessable":
            if not finding.record_evidence or not finding.procedure_references:
                raise ValueError(f"{finding.check_id}: assessment requires record and rule evidence")
            if finding.check_id=='consistency':
                cited={sources[r.source_id].document_id for r in finding.record_evidence}
                if 'MDR' not in cited or not cited.intersection({'DER','PESR'}):
                    raise ValueError('consistency: assessment requires event and MDR evidence')
        if finding.priority != "none" and not finding.study_action:
            raise ValueError(f"{finding.check_id}: a priority needs a study action")
