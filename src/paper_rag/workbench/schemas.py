from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchRequest(StrictRequest):
    query: str
    top_k: int = Field(8, ge=1, le=30)
    year_min: int | None = None
    year_max: int | None = None


class ContextPolicy(StrictRequest):
    include_pinned_evidence: bool = False
    include_notes: bool = False
    restrict_to_project_papers: bool = False


class QaRequest(StrictRequest):
    question: str
    paper_ids: list[str] | None = None
    resolved_question: str | None = None
    top_k: int = Field(8, ge=1, le=20)
    project_id: str | None = Field(None, min_length=1, max_length=180)
    context_policy: ContextPolicy | None = None


class SectionRequest(StrictRequest):
    paper_id: str
    section_name: str


class DiscoverRequest(StrictRequest):
    topic: str
    max_candidates: int = Field(10, ge=1, le=20)
    sources: list[str] | None = None


class ApprovalPayload(StrictRequest):
    approved: bool
    operation: str
    candidate_ids: list[int] = Field(default_factory=list)
    destination: str
    side_effects: list[str] = Field(default_factory=list)


class CandidateIngestRequest(StrictRequest):
    candidate_ids: list[int] = Field(..., min_length=1, max_length=5)
    force: bool = False
    approval: ApprovalPayload | None = None


class DshHandoffRequest(StrictRequest):
    question: str = Field(..., min_length=1, max_length=4000)
    paper_ids: list[str] = Field(default_factory=list, max_length=12)
    chunk_ids: list[str] = Field(default_factory=list, max_length=20)
    source: str = Field("workbench", max_length=80)


class ProjectCreateRequest(StrictRequest):
    name: str = Field(..., min_length=1, max_length=180)
    description: str = Field("", max_length=1000)


class ProjectUpdateRequest(StrictRequest):
    name: str | None = Field(None, min_length=1, max_length=180)
    description: str | None = Field(None, max_length=1000)


class ProjectPaperRequest(StrictRequest):
    paper_id: str = Field(..., min_length=1, max_length=180)
    title_snapshot: str = Field("", max_length=500)
    source: str = Field("manual", max_length=80)


class EvidencePinRequest(StrictRequest):
    chunk_id: str = Field(..., min_length=1, max_length=180)
    paper_id: str = Field(..., min_length=1, max_length=180)
    quote_snapshot: str = Field("", max_length=4000)
    source: str = Field("manual", max_length=80)
    score_snapshot: float | None = None
    label: str = Field("", max_length=120)
    note: str = Field("", max_length=2000)


class NoteRequest(StrictRequest):
    target_type: str = Field(..., min_length=1, max_length=20)
    target_id: str = Field(..., min_length=1, max_length=180)
    body: str = Field(..., min_length=1, max_length=10000)
    note_id: str | None = Field(None, min_length=1, max_length=180)


class SavedQuestionRequest(StrictRequest):
    question: str = Field(..., min_length=1, max_length=4000)
    answer: str = Field("", max_length=20000)
    citations: list[str] = Field(default_factory=list, max_length=100)
    chunk_ids: list[str] = Field(default_factory=list, max_length=200)
    trace_id: str | None = Field(None, max_length=180)
    abstain: Any | None = None
    context_policy: Any | None = None
    citation_papers: dict[str, str] = Field(default_factory=dict, max_length=200)


class ProjectHandoffRequest(StrictRequest):
    instruction: str = Field("", max_length=4000)


class CompareRequest(StrictRequest):
    paper_ids: list[str] = Field(default_factory=list, max_length=20)
    dimensions: list[str] = Field(default_factory=list, max_length=12)


McpEnvelope = dict[str, Any]
