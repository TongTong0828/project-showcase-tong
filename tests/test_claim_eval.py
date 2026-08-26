"""Tests for claim-level RAG evaluation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))


def test_loader_accepts_expected_claims_and_eval_tags(tmp_path: Path):
    from eval.loader import load_jsonl

    path = tmp_path / "claims.jsonl"
    path.write_text(
        json.dumps({
            "qid": "c001",
            "question": "What is Self-RAG?",
            "relevant_paper_ids": ["arxiv:2310.11511"],
            "expected_claims": [
                {
                    "id": "c001.1",
                    "text": "Self-RAG retrieves on demand.",
                    "accept_patterns": ["retriev"],
                    "supporting_chunk_ids": ["chunk-a"],
                }
            ],
            "eval_tags": ["query_mismatch", "method"],
        }) + "\n",
        encoding="utf-8",
    )

    item = load_jsonl(path)[0]

    assert item.expected_claims[0].id == "c001.1"
    assert item.expected_claims[0].accept_patterns == ["retriev"]
    assert item.expected_claims[0].supporting_chunk_ids == ["chunk-a"]
    assert item.eval_tags == ["query_mismatch", "method"]


def test_claim_metrics_match_patterns_case_and_regex():
    from eval.claim_metrics import score_claims

    result = score_claims(
        answer=(
            "Self-RAG retrieves on demand and uses reflection tokens. "
            "It judges whether evidence supports the answer."
        ),
        citation_ids=["chunk-a"],
        expected_claims=[
            {
                "id": "c1",
                "text": "Retrieves on demand",
                "accept_patterns": ["RETRIEVES on demand", "retrieve token"],
                "supporting_chunk_ids": ["chunk-a"],
            },
            {
                "id": "c2",
                "text": "Uses reflection tokens",
                "accept_patterns": ["re:reflection\\s+tokens?"],
                "supporting_chunk_ids": ["chunk-b"],
            },
            {
                "id": "c3",
                "text": "Ranks passages with BM25",
                "accept_patterns": ["bm25"],
                "supporting_chunk_ids": ["chunk-c"],
            },
        ],
    )

    assert result["claim_recall"] == 2 / 3
    assert result["grounded_claim_recall"] == 1 / 3
    assert result["covered_claim_ids"] == ["c1", "c2"]
    assert result["grounded_claim_ids"] == ["c1"]
    assert result["missing_claims"] == [{"id": "c3", "text": "Ranks passages with BM25"}]


def test_claim_metrics_skip_empty_claim_labels():
    from eval.claim_metrics import score_claims

    result = score_claims(answer="anything", citation_ids=[], expected_claims=[])

    assert result["claim_recall"] is None
    assert result["grounded_claim_recall"] is None
    assert result["missing_claims"] == []


def test_claim_metrics_use_claim_text_overlap_as_deterministic_fallback():
    from eval.claim_metrics import score_claims

    result = score_claims(
        answer='The model predicts a special "Retrieve" reflection token at inference time.',
        citation_ids=["chunk-a"],
        expected_claims=[
            {
                "id": "c1",
                "text": "Self-RAG predicts a retrieve decision token.",
                "accept_patterns": ["retrieve token"],
                "supporting_chunk_ids": ["chunk-a"],
            }
        ],
    )

    assert result["claim_recall"] == 1.0
    assert result["grounded_claim_recall"] == 1.0


def test_score_claim_answer_handles_no_evidence_without_zero_claim_score():
    from types import SimpleNamespace

    from eval.run_claim_eval import _score_claim_answer

    item = SimpleNamespace(
        expected_claims=[],
        must_not_contain=[],
        relevant_paper_ids=[],
    )
    out = {
        "answer": "The corpus does not contain enough evidence to answer.",
        "citations": [],
        "chunks": [],
        "trace": {"stopped_by": "no_evidence_abstain"},
    }

    scored = _score_claim_answer(out, item)

    assert scored["claim_recall"] is None
    assert scored["grounded_claim_recall"] is None
    assert scored["no_answer_ok"] == 1.0
    assert scored["forbidden_claim_violations"] == 0


def test_claim_aggregate_and_gate(tmp_path: Path):
    from eval.run_claim_eval import _aggregate_claim_rows, _evaluate_claim_gate

    rows = [
        {
            "qid": "c1",
            "category": "method",
            "expected_claim_count": 2,
            "claim_recall": 1.0,
            "grounded_claim_recall": 0.5,
            "forbidden_claim_violations": 0,
        },
        {
            "qid": "n1",
            "category": "no_evidence",
            "expected_claim_count": 0,
            "claim_recall": None,
            "grounded_claim_recall": None,
            "no_answer_ok": 1.0,
            "forbidden_claim_violations": 0,
        },
    ]
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(
        json.dumps({
            "claim_recall": {"min": 0.8},
            "grounded_claim_recall": {"min": 0.5},
            "no_answer_success_rate": {"min": 0.9},
            "forbidden_claim_violations": {"max": 0},
            "errors": {"max": 0},
        }),
        encoding="utf-8",
    )

    agg = _aggregate_claim_rows(rows)
    gate = _evaluate_claim_gate(agg, gate_path)

    assert agg["claim_recall"] == 1.0
    assert agg["grounded_claim_recall"] == 0.5
    assert agg["claim_label_coverage"] == 0.5
    assert agg["no_answer_success_rate"] == 1.0
    assert agg["skipped_metrics"]["claim_recall"] == 1
    assert gate["passed"] is True


def test_claim_markdown_report_lists_missing_claims(tmp_path: Path):
    from eval.run_claim_eval import _write_claim_report

    path = tmp_path / "claims.md"
    _write_claim_report(
        path,
        dataset="claims.jsonl",
        aggregate={"claim_recall": 0.5, "grounded_claim_recall": 0.25},
        rows=[
            {
                "qid": "c1",
                "category": "method",
                "question": "Q?",
                "claim_recall": 0.5,
                "grounded_claim_recall": 0.0,
                "missing_claims": [{"id": "c1.2", "text": "Missing claim"}],
            }
        ],
    )

    text = path.read_text(encoding="utf-8")
    assert "# RAG Claim Eval Report" in text
    assert "c1.2" in text
    assert "Missing claim" in text
