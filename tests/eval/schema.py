"""Evaluation set schema (pydantic) for paper_rag.

Each line of `qa_set.jsonl` parses to one `EvalItem`. Keep the schema small:
LLM-judge 'gold_answer' is optional; recall/citation metrics work with just
`relevant_paper_ids` (and optionally `relevant_chunk_ids` for fine-grained).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExpectedClaim(BaseModel):
    id: str = Field(..., description="Stable claim id within this eval item.")
    text: str = Field(..., description="Human-readable claim that should appear in the answer.")
    accept_patterns: list[str] = Field(
        default_factory=list,
        description="Case-insensitive substrings, or regexes prefixed with 're:', that satisfy the claim.",
    )
    supporting_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Chunk ids that can ground this claim when cited by the answer.",
    )


class EvalItem(BaseModel):
    qid: str = Field(..., description="Stable id for the question")
    question: str
    intent: Literal["factual", "reasoning", "explore"] = "reasoning"
    category: str | None = Field(
        None,
        description="Optional reporting bucket, e.g. compare, evaluation, ambiguous, no_evidence.",
    )

    relevant_paper_ids: list[str] = Field(
        default_factory=list,
        description="Papers that SHOULD appear in the cited evidence (paper-level recall).",
    )
    relevant_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Optional chunk-level ground truth for tighter recall@k.",
    )
    citation_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Optional chunk ids that directly support answer citations. "
                    "Falls back to relevant_chunk_ids when empty.",
    )
    irrelevant_paper_ids: list[str] = Field(
        default_factory=list,
        description="Papers that MUST NOT appear in top-k retrieval. Used to "
                    "compute false_positive_rate. Pick obviously-wrong topic "
                    "papers from your corpus (e.g. for an NLP question, list "
                    "a CV paper). Empty list = metric skipped.",
    )

    must_contain: list[str] = Field(
        default_factory=list,
        description="Substrings the answer must contain (case-insensitive). "
                    "Used as a cheap proxy for correctness without LLM-judge.",
    )
    must_not_contain: list[str] = Field(
        default_factory=list,
        description="Substrings that MUST NOT appear (e.g., a wrong number).",
    )
    gold_answer: str | None = Field(
        None,
        description="Reference answer for LLM-judge; if None, judge is skipped.",
    )
    expected_claims: list[ExpectedClaim] = Field(
        default_factory=list,
        description="Claim-level answer labels for semantic recall evaluation.",
    )
    eval_tags: list[str] = Field(
        default_factory=list,
        description="Optional analysis tags, e.g. query_mismatch, compare, multi_hop, no_evidence.",
    )
    notes: str | None = None
