"""Tests for M5 P2 features (pure-logic only)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_split_arxiv_version():
    from paper_rag.utils.ids import split_arxiv_version

    assert split_arxiv_version("2310.12345") == ("2310.12345", None)
    assert split_arxiv_version("2310.12345v2") == ("2310.12345", "v2")
    assert split_arxiv_version("https://arxiv.org/abs/2310.12345v3") == ("2310.12345", "v3")
    assert split_arxiv_version("not-arxiv-at-all") == (None, None)


def test_grade_sections_complete():
    from paper_rag.chunk.sanity import grade_sections

    assert grade_sections([
        "Abstract", "1 Introduction", "2 Method", "3 Experiments",
        "4 Results", "5 Conclusion",
    ]) == "complete"


def test_grade_sections_partial_minimal_broken():
    from paper_rag.chunk.sanity import grade_sections

    assert grade_sections(["Introduction", "Approach", "Discussion"]) == "partial"
    assert grade_sections(["Abstract"]) == "minimal"
    assert grade_sections(["Acknowledgments", "References"]) == "broken"
    assert grade_sections([]) == "broken"


def test_false_positive_rate():
    from eval.metrics import false_positive_rate

    sys.path.insert(0, str(ROOT / "tests"))
    from eval.metrics import false_positive_rate as fpr

    assert fpr(["a", "b", "c"], ["d", "e"], k=3) == 0.0
    assert fpr(["a", "b", "d"], ["d", "e"], k=3) == 0.5
    assert fpr(["d", "e"], ["d", "e"], k=2) == 1.0
    # k truncates predictions
    assert fpr(["a", "b", "c", "d"], ["d"], k=3) == 0.0
    # missing GT -> None
    assert fpr(["a"], [], k=3) is None


def test_qa_cache_key_normalization():
    from paper_rag.rag.qa_cache import _make_key, _norm_question

    assert _norm_question("  Hello   World  ") == "hello world"
    # Same key regardless of paper_ids order
    k1 = _make_key("What is X?", ["arxiv:1", "arxiv:2"])
    k2 = _make_key("What is X?", ["arxiv:2", "arxiv:1"])
    assert k1 == k2
    # Different paper set -> different key
    k3 = _make_key("What is X?", ["arxiv:3"])
    assert k1 != k3
    # Different question -> different key
    k4 = _make_key("What is Y?", ["arxiv:1", "arxiv:2"])
    assert k1 != k4


def test_qa_cache_key_includes_user_and_effective_context():
    from paper_rag.rag.qa_cache import _make_key

    a = _make_key(
        "How does FLARE retrieve?\n\nwiki_context_fingerprint:w1\npipeline:qra-v1",
        ["p1"],
        user_id="alice",
    )
    b = _make_key(
        "How does FLARE retrieve?\n\nwiki_context_fingerprint:w1\npipeline:qra-v1",
        ["p1"],
        user_id="bob",
    )
    c = _make_key(
        "How does Self-RAG retrieve?\n\nwiki_context_fingerprint:w1\npipeline:qra-v1",
        ["p1"],
        user_id="alice",
    )

    assert a != b
    assert a != c


def test_cache_hit_returns_rehydrated_chunks(monkeypatch, tmp_path):
    from sqlalchemy import create_engine

    from paper_rag.rag import qa_cache
    from paper_rag.store import sqlite_store

    engine = create_engine(f"sqlite:///{tmp_path / 'cache.sqlite'}")
    monkeypatch.setattr(sqlite_store, "get_engine", lambda: engine)
    monkeypatch.setattr(qa_cache, "_enabled", lambda: True)
    sqlite_store.SQLModel.metadata.create_all(engine)
    sqlite_store.upsert_sections_and_chunks(
        "p1",
        [],
        [
            {
                "chunk_id": "c1",
                "paper_id": "p1",
                "text": "cached evidence",
                "context_text": "cached evidence",
            }
        ],
    )
    qa_cache._TABLE_READY = False

    answer = {
        "answer": "cached [chunk:c1]",
        "citations": ["c1"],
        "chunks": [{"chunk_id": "c1", "paper_id": "p1", "text": "cached evidence"}],
        "trace": {"trace_id": "old"},
    }
    qa_cache.put("effective\n\npipeline:qra-v1", ["p1"], answer, user_id="alice")
    cached = qa_cache.get("effective\n\npipeline:qra-v1", ["p1"], user_id="alice")

    assert cached is not None
    assert cached["chunks"][0]["chunk_id"] == "c1"
    assert cached["chunks"][0]["text"] == "cached evidence"
