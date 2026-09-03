"""Tests for deterministic evidence selection before QA generation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_select_evidence_limits_chunks_and_preserves_compare_coverage():
    from paper_rag.rag.evidence_select import select_evidence

    chunks = [
        {
            "chunk_id": "aaaaaaaaaa",
            "paper_id": "paper-self",
            "text": "Self-RAG uses reflection tokens for retrieval decisions.",
            "score_rerank": 0.92,
            "score_rrf": 0.05,
        },
        {
            "chunk_id": "bbbbbbbbbb",
            "paper_id": "paper-self",
            "text": "Self-RAG critiques support and usefulness.",
            "score_rerank": 0.88,
            "score_rrf": 0.04,
        },
        {
            "chunk_id": "cccccccccc",
            "paper_id": "paper-self",
            "text": "Background material about language models.",
            "score_rerank": 0.86,
            "score_rrf": 0.03,
        },
        {
            "chunk_id": "dddddddddd",
            "paper_id": "paper-flare",
            "text": "FLARE retrieves when low-confidence tokens are predicted.",
            "score_rerank": 0.82,
            "score_rrf": 0.02,
        },
        {
            "chunk_id": "eeeeeeeeee",
            "paper_id": "paper-flare",
            "text": "FLARE iteratively anticipates future sentences.",
            "score_rerank": 0.80,
            "score_rrf": 0.01,
        },
    ]

    selected, trace = select_evidence(
        "Compare Self-RAG and FLARE retrieval timing",
        chunks,
        intent="compare",
    )

    assert len(selected) <= 4
    assert [c["chunk_id"] for c in selected] == [
        "aaaaaaaaaa",
        "bbbbbbbbbb",
        "dddddddddd",
        "eeeeeeeeee",
    ]
    assert trace["selected_chunk_ids"] == [c["chunk_id"] for c in selected]
    assert trace["max_chunks"] == 4
    assert trace["max_per_paper"] == 2


def test_select_evidence_scores_lexical_overlap_when_scores_tie():
    from paper_rag.rag.evidence_select import select_evidence

    chunks = [
        {
            "chunk_id": "aaaaaaaaaa",
            "paper_id": "paper-a",
            "text": "Generic background text.",
            "score_rerank": 0.5,
        },
        {
            "chunk_id": "bbbbbbbbbb",
            "paper_id": "paper-b",
            "text": "Query rewriting improves retrieval in advanced RAG.",
            "score_rerank": 0.5,
        },
    ]

    selected, trace = select_evidence("How does query rewriting improve RAG retrieval?", chunks)

    assert selected[0]["chunk_id"] == "bbbbbbbbbb"
    assert trace["candidates"][0]["lexical_overlap"] > trace["candidates"][1]["lexical_overlap"]


def test_select_evidence_ignores_question_stopwords_for_focus_terms():
    from paper_rag.rag.evidence_select import select_evidence

    chunks = [
        {
            "chunk_id": "generic-rag",
            "paper_id": "paper-a",
            "text": "What is the origin of RAG and why use it in generation systems?",
            "score_rerank": 0.5,
        },
        {
            "chunk_id": "reranking",
            "paper_id": "paper-b",
            "text": (
                "RAG reranking reorders retrieved document chunks to highlight "
                "the most relevant evidence before generation."
            ),
            "score_rerank": 0.5,
        },
    ]

    selected, trace = select_evidence(
        "What is reranking in RAG and why use it?",
        chunks,
        max_chunks=1,
    )

    assert selected[0]["chunk_id"] == "reranking"
    assert trace["candidates"][0]["chunk_id"] == "reranking"
