from __future__ import annotations

from sqlalchemy import create_engine


def _patch_engine(monkeypatch, tmp_path):
    from paper_rag.store import sqlite_store

    engine = create_engine(f"sqlite:///{tmp_path / 'turns.sqlite'}")
    monkeypatch.setattr(sqlite_store, "get_engine", lambda: engine)
    return engine


def test_recent_turns_are_user_and_conversation_scoped(monkeypatch, tmp_path):
    _patch_engine(monkeypatch, tmp_path)

    from paper_rag.rag import conversation_turn_store as store

    store._TABLE_READY = False
    store.append_turn(
        user_id="alice",
        conversation_id="same",
        raw_question="raw a",
        effective_question="effective a",
        answer="answer a",
        citations=["c1"],
        paper_ids=["p1"],
        trace={"trace_id": "t-a"},
        resolution_source="outer_checkpoint",
    )
    store.append_turn(
        user_id="bob",
        conversation_id="same",
        raw_question="raw b",
        effective_question="effective b",
        answer="answer b",
        citations=["c2"],
        paper_ids=["p2"],
        trace={"trace_id": "t-b"},
        resolution_source="paper_rag_recent_turns",
    )

    alice = store.recent_turns(user_id="alice", conversation_id="same")
    bob = store.recent_turns(user_id="bob", conversation_id="same")

    assert [turn.raw_question for turn in alice] == ["raw a"]
    assert [turn.raw_question for turn in bob] == ["raw b"]
    assert alice[0].effective_question == "effective a"
    assert bob[0].paper_ids == ["p2"]


def test_history_facade_reads_canonical_turns(monkeypatch, tmp_path):
    _patch_engine(monkeypatch, tmp_path)

    from paper_rag.rag import conversation_turn_store as store
    from paper_rag.rag import history

    store._TABLE_READY = False
    history._TABLE_READY = False
    history.append("conv-h", "Q1", "A1", ["c1"])
    history.append("conv-h", "Q2", "A2", ["c2"])

    assert history.recent("conv-h", limit=2) == [("Q1", "A1"), ("Q2", "A2")]


def test_legacy_research_memory_rows_migrate_under_system_user(monkeypatch, tmp_path):
    engine = _patch_engine(monkeypatch, tmp_path)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE research_memory_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                citations_json TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                paper_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO research_memory_turns
            (conversation_id, question, answer, citations_json, trace_json, paper_ids_json, created_at)
            VALUES ('legacy', 'Legacy Q', 'Legacy A', '["c1"]', '{"trace_id":"old"}', '["p1"]', '2026-07-27T00:00:00')
            """
        )

    from paper_rag.rag import conversation_turn_store as store

    store._TABLE_READY = False
    turns = store.recent_turns(user_id="system", conversation_id="legacy")

    assert len(turns) == 1
    assert turns[0].raw_question == "Legacy Q"
    assert turns[0].resolution_source == "legacy_research_memory"


def test_legacy_research_memory_rows_do_not_migrate_to_named_users(monkeypatch, tmp_path):
    engine = _patch_engine(monkeypatch, tmp_path)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE research_memory_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                citations_json TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                paper_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO research_memory_turns
            (conversation_id, question, answer, citations_json, trace_json, paper_ids_json, created_at)
            VALUES ('legacy', 'Legacy Q', 'Legacy A', '["c1"]', '{"trace_id":"old"}', '["p1"]', '2026-07-27T00:00:00')
            """
        )

    from paper_rag.rag import conversation_turn_store as store

    store._TABLE_READY = False
    alice_turns = store.recent_turns(user_id="alice", conversation_id="legacy")
    system_turns = store.recent_turns(user_id="system", conversation_id="legacy")

    assert alice_turns == []
    assert [turn.raw_question for turn in system_turns] == ["Legacy Q"]
