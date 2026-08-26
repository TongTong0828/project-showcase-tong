"""Tests for the higher-level eval harness aggregation and gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))


def test_aggregate_skips_unlabeled_chunk_metrics():
    from eval.run_eval import _aggregate

    rows = [
        {
            "qid": "q1",
            "category": "factual",
            "expected_relevant_paper_count": 1,
            "paper_recall@k": 1.0,
            "paper_mrr": 1.0,
            "paper_precision@k": 0.5,
            "paper_ndcg@k": 1.0,
        },
        {
            "qid": "q2",
            "category": "no_evidence",
            "expected_relevant_paper_count": 0,
            "paper_recall@k": 0.0,
            "paper_mrr": 0.0,
            "paper_precision@k": None,
            "paper_ndcg@k": None,
            "no_answer_ok": 1.0,
        },
    ]

    agg = _aggregate(rows)

    assert agg["chunk_recall@k"] is None
    assert agg["chunk_mrr"] is None
    assert agg["cite_precision"] is None
    assert agg["chunk_label_coverage"] == 0.0
    assert agg["skipped_metrics"]["chunk_recall@k"] == 2
    assert agg["by_category"]["factual"]["positive_paper_recall@k"] == 1.0
    assert agg["by_category"]["no_evidence"]["no_answer_success_rate"] == 1.0


def test_aggregate_reports_chunk_and_citation_metrics_when_labeled():
    from eval.run_eval import _aggregate

    rows = [
        {
            "qid": "q1",
            "category": "reasoning",
            "expected_relevant_paper_count": 1,
            "has_chunk_labels": True,
            "paper_recall@k": 1.0,
            "paper_mrr": 1.0,
            "chunk_recall@k": 0.5,
            "chunk_mrr": 1.0,
            "chunk_precision@k": 0.25,
            "chunk_ndcg@k": 0.631,
            "answer": "ok",
            "cite_existence": 1.0,
            "cite_precision": 0.5,
            "cite_paper_precision": 1.0,
            "cite_recall": 0.5,
            "must_contain": 1.0,
            "violations": 0,
        }
    ]

    agg = _aggregate(rows)

    assert agg["positive_chunk_recall@k"] == 0.5
    assert agg["chunk_mrr"] == 1.0
    assert agg["chunk_precision@k"] == 0.25
    assert agg["chunk_ndcg@k"] == 0.631
    assert agg["cite_precision"] == 0.5
    assert agg["cite_paper_precision"] == 1.0
    assert agg["cite_recall"] == 0.5
    assert agg["chunk_label_coverage"] == 1.0


def test_loader_accepts_citation_chunk_ids(tmp_path: Path):
    from eval.loader import load_jsonl

    path = tmp_path / "qa.jsonl"
    path.write_text(
        json.dumps({
            "qid": "q1",
            "question": "Q?",
            "relevant_paper_ids": ["paper-a"],
            "relevant_chunk_ids": ["retrieval-core"],
            "citation_chunk_ids": ["citation-ok"],
        }) + "\n",
        encoding="utf-8",
    )

    item = load_jsonl(path)[0]

    assert item.relevant_chunk_ids == ["retrieval-core"]
    assert item.citation_chunk_ids == ["citation-ok"]


def test_score_answer_uses_citation_labels_and_records_details():
    from types import SimpleNamespace

    from eval.run_eval import _score_answer

    item = SimpleNamespace(
        question="Q?",
        relevant_paper_ids=["paper-a"],
        relevant_chunk_ids=["retrieval-core"],
        citation_chunk_ids=["citation-ok"],
        must_contain=["answer"],
        must_not_contain=[],
        gold_answer=None,
    )
    out = {
        "answer": "answer [chunk:citation-ok] [chunk:right-paper-bg] [chunk:wrong-paper]",
        "citations": ["citation-ok", "right-paper-bg", "wrong-paper"],
        "chunks": [
            {
                "chunk_id": "retrieval-core",
                "paper_id": "paper-a",
                "title": "Paper A",
                "section": "Intro",
            },
            {
                "chunk_id": "citation-ok",
                "paper_id": "paper-a",
                "title": "Paper A",
                "section": "Method",
            },
            {
                "chunk_id": "right-paper-bg",
                "paper_id": "paper-a",
                "title": "Paper A",
                "section": "Related Work",
            },
            {
                "chunk_id": "wrong-paper",
                "paper_id": "paper-b",
                "title": "Paper B",
                "section": "Method",
            },
        ],
        "trace": {},
    }

    scored = _score_answer(out, item, run_judge=False)

    assert scored["cite_precision"] == 1 / 3
    assert scored["cite_recall"] == 1.0
    assert scored["cite_paper_precision"] == 2 / 3
    assert scored["citation_details"][0]["chunk_id"] == "citation-ok"
    assert scored["citation_details"][0]["matches_citation_label"] is True
    assert scored["citation_details"][1]["matches_relevant_paper"] is True
    assert scored["citation_details"][1]["matches_citation_label"] is False
    assert scored["citation_details"][2]["matches_relevant_paper"] is False


def test_citation_audit_report_lists_low_precision_rows(tmp_path: Path):
    from eval.run_eval import _write_citation_audit_report

    path = tmp_path / "audit.md"
    _write_citation_audit_report(
        path,
        aggregate={"cite_precision": 0.5, "cite_paper_precision": 1.0},
        items=[
            {
                "qid": "q1",
                "category": "method",
                "question": "Q?",
                "cite_precision": 0.0,
                "cite_paper_precision": 1.0,
                "relevant_chunk_ids": ["retrieval-core"],
                "citation_chunk_ids": ["citation-ok"],
                "citation_details": [
                    {
                        "chunk_id": "right-paper-bg",
                        "paper_id": "paper-a",
                        "title": "Paper A",
                        "section": "Background",
                        "rank": 2,
                        "matches_citation_label": False,
                        "matches_relevant_paper": True,
                    }
                ],
            }
        ],
    )

    text = path.read_text(encoding="utf-8")
    assert "# RAG Citation Audit" in text
    assert "q1" in text
    assert "right-paper-bg" in text
    assert "right_paper_wrong_chunk" in text


def test_retrieval_fpr_only_penalizes_false_positives_before_evidence():
    from types import SimpleNamespace

    from eval.run_eval import _score_retrieval

    item = SimpleNamespace(
        relevant_paper_ids=["paper-good"],
        relevant_chunk_ids=[],
        irrelevant_paper_ids=["paper-bad"],
    )

    after_evidence = _score_retrieval(
        [
            {"paper_id": "paper-good", "chunk_id": "c-good"},
            {"paper_id": "paper-bad", "chunk_id": "c-bad"},
        ],
        item,
        10,
    )
    before_evidence = _score_retrieval(
        [
            {"paper_id": "paper-bad", "chunk_id": "c-bad"},
            {"paper_id": "paper-good", "chunk_id": "c-good"},
        ],
        item,
        10,
    )

    assert after_evidence["fpr@k"] == 0.0
    assert before_evidence["fpr@k"] == 1.0


def test_print_summary_handles_skipped_citation_precision(capsys):
    from eval.run_eval import _print_summary

    _print_summary(
        1,
        1,
        {
            "qid": "n001",
            "paper_recall@k": 0.0,
            "paper_mrr": 0.0,
            "n_citations": 0,
            "must_contain": 1.0,
            "cite_precision": None,
        },
    )

    out = capsys.readouterr().out
    assert "n001" in out
    assert "cite_p" not in out


def test_gate_evaluation_and_markdown_report(tmp_path: Path):
    from eval.run_eval import _evaluate_gate, _write_markdown_report

    gate_path = tmp_path / "gate.json"
    gate_path.write_text(
        json.dumps({
            "retrieval_only": {
                "positive_paper_recall@k": {"min": 0.95},
                "fpr@k": {"max": 0.05},
                "errors": {"max": 0},
            }
        }),
        encoding="utf-8",
    )
    aggregate = {
        "positive_paper_recall@k": 1.0,
        "fpr@k": 0.0,
        "errors": 0,
        "n_items": 2,
    }

    result = _evaluate_gate(aggregate, gate_path, mode="retrieval_only")

    assert result["passed"] is True
    assert result["checks"][0]["metric"] == "positive_paper_recall@k"

    report_path = tmp_path / "report.md"
    _write_markdown_report(
        report_path,
        mode="retrieval_only",
        dataset="tiny.jsonl",
        aggregate=aggregate | {"gate": result},
        items=[{"qid": "q1", "paper_recall@k": 1.0, "paper_mrr": 1.0}],
    )
    text = report_path.read_text(encoding="utf-8")
    assert "# RAG Eval Report" in text
    assert "positive_paper_recall@k" in text
    assert "q1" in text


def test_ablation_summary_skips_unlabeled_metrics():
    from eval.run_ablation import _summarize_strategy

    summary = _summarize_strategy([
        {
            "expected_relevant_paper_count": 1,
            "paper_recall@k": 1.0,
            "paper_mrr": 0.5,
            "chunk_recall@k": None,
        },
        {
            "expected_relevant_paper_count": 0,
            "paper_recall@k": 0.0,
            "paper_mrr": 0.0,
            "chunk_recall@k": None,
        },
    ])

    assert summary["paper_recall@k"] == 0.5
    assert summary["positive_paper_recall@k"] == 1.0
    assert summary["paper_mrr"] == 0.25
    assert summary["chunk_recall@k"] is None
