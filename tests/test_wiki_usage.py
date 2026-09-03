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


def test_record_consumption_writes_one_row_per_entry_and_paper(tmp_path, monkeypatch):
    _point_sqlite_to_tmp(monkeypatch, tmp_path)
    from paper_rag.wiki import usage

    usage.record_consumption(
        question="What is RAG?",
        paper_ids=["paper-1"],
        wiki_context={
            "fingerprint": "concept:rag:2",
            "entries": [{"entry_id": "concept:rag", "name": "RAG", "version": 2}],
        },
        trace_id="t1",
    )

    assert usage.consumed_paper_ids() == {"paper-1"}
