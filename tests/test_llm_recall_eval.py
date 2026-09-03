"""Tests for LLM-assisted retrieval recall reporting."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))


def test_summarize_with_baseline_reports_gain_and_harm():
    from eval.run_llm_recall import _summarize_with_baseline

    baseline_rows = [
        {"qid": "q1", "chunk_recall@k": 0.0, "paper_recall@k": 0.0, "latency_ms": 10.0},
        {"qid": "q2", "chunk_recall@k": 1.0, "paper_recall@k": 1.0, "latency_ms": 10.0},
        {"qid": "q3", "chunk_recall@k": None, "paper_recall@k": 0.0, "latency_ms": 10.0},
    ]
    strategy_rows = [
        {"qid": "q1", "chunk_recall@k": 1.0, "paper_recall@k": 1.0, "latency_ms": 30.0},
        {"qid": "q2", "chunk_recall@k": 0.0, "paper_recall@k": 1.0, "latency_ms": 30.0},
        {"qid": "q3", "chunk_recall@k": None, "paper_recall@k": 1.0, "latency_ms": 30.0},
    ]

    summary = _summarize_with_baseline(strategy_rows, baseline_rows)

    assert summary["rewrite_gain_count"] == 2
    assert summary["rewrite_harm_count"] == 1
    assert summary["rewrite_harm_rate"] == 1 / 3
    assert summary["latency_ms"] == 30.0


def test_strategy_no_rewrite_payload_contains_original_query_only():
    from eval.run_llm_recall import _no_rewrite

    payload = _no_rewrite("What is HyDE?")

    assert payload["dense_queries"] == ["What is HyDE?"]
    assert payload["bm25_query"] == "What is HyDE?"
    assert payload["raw"]["strategy"] == "baseline_no_rewrite"


def test_write_llm_recall_report(tmp_path: Path):
    from eval.run_llm_recall import _write_llm_recall_report

    path = tmp_path / "llm_recall.md"
    _write_llm_recall_report(
        path,
        dataset="claims.jsonl",
        result={
            "baseline_no_rewrite": {
                "summary": {
                    "positive_paper_recall@k": 0.8,
                    "positive_chunk_recall@k": 0.6,
                    "rewrite_gain_count": 0,
                    "rewrite_harm_rate": 0.0,
                    "latency_ms": 10.0,
                    "errors": 0,
                }
            },
            "llm_rewrite_hyde": {
                "summary": {
                    "positive_paper_recall@k": 0.9,
                    "positive_chunk_recall@k": 0.7,
                    "rewrite_gain_count": 3,
                    "rewrite_harm_rate": 0.1,
                    "latency_ms": 40.0,
                    "errors": 0,
                }
            },
        },
    )

    text = path.read_text(encoding="utf-8")
    assert "# LLM-Assisted Retrieval Recall Report" in text
    assert "baseline_no_rewrite" in text
    assert "llm_rewrite_hyde" in text
