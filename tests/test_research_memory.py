from __future__ import annotations

import json


def _patch_sqlite_engine(monkeypatch, tmp_path):
    from sqlalchemy import create_engine

    from paper_rag.store import sqlite_store

    engine = create_engine(f"sqlite:///{tmp_path / 'research_memory.db'}")
    monkeypatch.setattr(sqlite_store, "get_engine", lambda: engine)
    return engine


def test_research_memory_load_empty_returns_safe_defaults(monkeypatch, tmp_path):
    _patch_sqlite_engine(monkeypatch, tmp_path)

    from paper_rag.rag import research_memory

    research_memory._TABLE_READY = False
    memory = research_memory.load_for_question("conv-empty")

    assert memory["conversation_id"] == "conv-empty"
    assert memory["recent_turns"] == []
    assert memory["session_summary"] == ""
    assert memory["has_compressed_memory"] is False
    assert memory["memory_role"] == "query_context_only_not_evidence"


def test_research_memory_compresses_after_seventh_turn(monkeypatch, tmp_path):
    _patch_sqlite_engine(monkeypatch, tmp_path)

    from paper_rag.rag import research_memory

    research_memory._TABLE_READY = False

    def fake_chat(messages, **kwargs):
        assert "not evidence" in messages[-1]["content"].lower()
        return json.dumps(
            {
                "session_summary": "The user is comparing Self-RAG retrieval decisions.",
                "research_memory": {
                    "current_topics": ["Self-RAG"],
                    "read_papers": ["arxiv:2310.11511"],
                    "confirmed_findings": ["Self-RAG uses reflection tokens."],
                    "open_questions": ["Compare Self-RAG with FLARE."],
                    "preferences": ["Prefer citation-grounded answers."],
                },
            }
        )

    monkeypatch.setattr(research_memory, "chat", fake_chat)

    last_meta = None
    for i in range(7):
        last_meta = research_memory.append(
            "conv-memory",
            f"Question {i} about Self-RAG?",
            f"Answer {i} says Self-RAG uses reflection tokens.",
            ["chunk:abc123"],
            trace={"chunks": [{"paper_id": "arxiv:2310.11511"}]},
        )

    assert last_meta["compressed"] is True

    memory = research_memory.load_for_question("conv-memory")
    assert memory["has_compressed_memory"] is True
    assert memory["session_summary"].startswith("The user is comparing")
    assert memory["research_memory"]["current_topics"] == ["Self-RAG"]
    assert memory["research_memory"]["read_papers"] == ["arxiv:2310.11511"]
    assert len(memory["recent_turns"]) == 3


def test_research_memory_falls_back_when_summarizer_fails(monkeypatch, tmp_path):
    _patch_sqlite_engine(monkeypatch, tmp_path)

    from paper_rag.rag import research_memory

    research_memory._TABLE_READY = False
    monkeypatch.setattr(
        research_memory,
        "chat",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("llm unavailable")),
    )

    for i in range(7):
        research_memory.append(
            "conv-fallback",
            f"Question {i}?",
            f"Answer {i} with a citation.",
            ["chunk:def456"],
        )

    memory = research_memory.load_for_question("conv-fallback")
    assert memory["has_compressed_memory"] is True
    assert "Question 6?" in memory["session_summary"]
    assert memory["research_memory"]["open_questions"] == ["Question 6?"]


def test_research_memory_is_user_scoped(monkeypatch, tmp_path):
    from paper_rag.rag import conversation_turn_store as store
    from paper_rag.rag import research_memory

    _patch_sqlite_engine(monkeypatch, tmp_path)
    store._TABLE_READY = False
    research_memory._TABLE_READY = False

    research_memory.append(
        "conv",
        "Alice question",
        "Alice answer",
        ["c1"],
        trace={"chunks": [{"paper_id": "paper-a"}]},
        user_id="alice",
    )
    research_memory.append(
        "conv",
        "Bob question",
        "Bob answer",
        ["c2"],
        trace={"chunks": [{"paper_id": "paper-b"}]},
        user_id="bob",
    )

    alice = research_memory.load_for_question("conv", user_id="alice")
    bob = research_memory.load_for_question("conv", user_id="bob")

    assert [turn["question"] for turn in alice["recent_turns"]] == ["Alice question"]
    assert [turn["question"] for turn in bob["recent_turns"]] == ["Bob question"]
