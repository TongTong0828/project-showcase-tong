from __future__ import annotations

from types import SimpleNamespace


def _point_sqlite_to_tmp(monkeypatch, tmp_path):
    from paper_rag.store import sqlite_store

    sqlite_store._ENGINE = None
    monkeypatch.setattr(
        sqlite_store.cfg,
        "load",
        lambda: SimpleNamespace(paths=SimpleNamespace(sqlite_path=str(tmp_path / "papers.sqlite"))),
    )
    return sqlite_store


def test_review_queue_dedupes_recent_events(tmp_path, monkeypatch):
    _point_sqlite_to_tmp(monkeypatch, tmp_path)
    from paper_rag.wiki import review_queue

    first = review_queue.enqueue(
        "qa_weak_evidence",
        concept="RAG",
        paper_id="paper-1",
        question="What is RAG?",
        reason="weak_evidence",
    )
    second = review_queue.enqueue(
        "qa_weak_evidence",
        concept="RAG",
        paper_id="paper-1",
        question="What is RAG again?",
        reason="weak_evidence",
    )

    assert first == second
    assert review_queue.count_pending() == 1


def test_review_queue_recent_returns_payload(tmp_path, monkeypatch):
    _point_sqlite_to_tmp(monkeypatch, tmp_path)
    from paper_rag.wiki import review_queue

    rid = review_queue.enqueue(
        "qa_no_chunks",
        concept="Contrastive Learning",
        paper_id=None,
        question="How is contrastive learning evaluated?",
        reason="no_chunks",
        payload={"trace_id": "t1"},
    )

    rows = review_queue.recent(limit=5)

    assert rows[0]["id"] == rid
    assert rows[0]["status"] == "pending"
    assert rows[0]["concept"] == "Contrastive Learning"
    assert rows[0]["payload"] == {"trace_id": "t1"}
