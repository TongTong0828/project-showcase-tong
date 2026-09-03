"""Tenant-scoped conversation turn storage for Paper RAG QA."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text

_TABLE_READY = False
_TABLE_ENGINE_KEY: int | None = None


@dataclass(frozen=True)
class ConversationTurn:
    raw_question: str
    effective_question: str
    answer: str
    citations: list[str]
    paper_ids: list[str]
    trace: dict[str, Any]
    resolution_source: str
    created_at: str


def _json_loads(value: str | None, default):
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _ensure_tables() -> None:
    global _TABLE_READY, _TABLE_ENGINE_KEY
    from ..store.sqlite_store import get_engine

    engine = get_engine()
    engine_key = id(engine)
    if _TABLE_READY and _TABLE_ENGINE_KEY == engine_key:
        return

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                raw_question TEXT NOT NULL,
                effective_question TEXT NOT NULL,
                answer TEXT NOT NULL,
                citations_json TEXT NOT NULL,
                paper_ids_json TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                resolution_source TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS conversation_turns_user_conv_id_idx "
            "ON conversation_turns(user_id, conversation_id, id)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS conversation_turns_user_conv_created_idx "
            "ON conversation_turns(user_id, conversation_id, created_at)"
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                session_summary TEXT NOT NULL,
                research_memory_json TEXT NOT NULL,
                n_turns INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, conversation_id)
            )
            """
        )
    _TABLE_READY = True
    _TABLE_ENGINE_KEY = engine_key


def _legacy_table_exists(conn, name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": name},
    ).fetchone()
    return row is not None


def _canonical_count(conn, user_id: str, conversation_id: str) -> int:
    row = conn.execute(
        text(
            "SELECT COUNT(*) FROM conversation_turns "
            "WHERE user_id = :u AND conversation_id = :c"
        ),
        {"u": user_id, "c": conversation_id},
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _insert_turn(
    conn,
    *,
    user_id: str,
    conversation_id: str,
    raw_question: str,
    effective_question: str,
    answer: str,
    citations: list[str],
    paper_ids: list[str],
    trace: dict[str, Any],
    resolution_source: str,
    created_at: str,
) -> None:
    conn.execute(
        text(
            "INSERT INTO conversation_turns "
            "(user_id, conversation_id, raw_question, effective_question, answer, "
            "citations_json, paper_ids_json, trace_json, resolution_source, created_at) "
            "VALUES (:u, :c, :rq, :eq, :a, :ci, :p, :tr, :rs, :t)"
        ),
        {
            "u": user_id or "system",
            "c": conversation_id,
            "rq": raw_question,
            "eq": effective_question,
            "a": answer,
            "ci": json.dumps(citations, ensure_ascii=False),
            "p": json.dumps(paper_ids, ensure_ascii=False),
            "tr": json.dumps(trace, ensure_ascii=False),
            "rs": resolution_source,
            "t": created_at,
        },
    )


def _migrate_legacy_if_empty(user_id: str, conversation_id: str) -> None:
    if not conversation_id:
        return
    if (user_id or "system") != "system":
        return
    from ..store.sqlite_store import get_engine

    with get_engine().begin() as conn:
        if _canonical_count(conn, user_id, conversation_id) > 0:
            return
        if _legacy_table_exists(conn, "research_memory_turns"):
            rows = list(
                conn.execute(
                    text(
                        "SELECT question, answer, citations_json, trace_json, "
                        "paper_ids_json, created_at FROM research_memory_turns "
                        "WHERE conversation_id = :c ORDER BY id ASC"
                    ),
                    {"c": conversation_id},
                )
            )
            for row in rows:
                question = str(row[0] or "")
                _insert_turn(
                    conn,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    raw_question=question,
                    effective_question=question,
                    answer=str(row[1] or ""),
                    citations=_json_loads(row[2], []),
                    trace=_json_loads(row[3], {}),
                    paper_ids=_json_loads(row[4], []),
                    resolution_source="legacy_research_memory",
                    created_at=str(row[5] or datetime.utcnow().isoformat()),
                )
        if _canonical_count(conn, user_id, conversation_id) > 0:
            return
        if _legacy_table_exists(conn, "qa_history"):
            rows = list(
                conn.execute(
                    text(
                        "SELECT question, answer, citations_json, created_at "
                        "FROM qa_history WHERE conversation_id = :c ORDER BY id ASC"
                    ),
                    {"c": conversation_id},
                )
            )
            for row in rows:
                question = str(row[0] or "")
                _insert_turn(
                    conn,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    raw_question=question,
                    effective_question=question,
                    answer=str(row[1] or ""),
                    citations=_json_loads(row[2], []),
                    trace={},
                    paper_ids=[],
                    resolution_source="legacy_qa_history",
                    created_at=str(row[3] or datetime.utcnow().isoformat()),
                )


def append_turn(
    *,
    user_id: str,
    conversation_id: str,
    raw_question: str,
    effective_question: str,
    answer: str,
    citations: list[str],
    paper_ids: list[str],
    trace: dict,
    resolution_source: str,
) -> None:
    if not conversation_id:
        return
    from ..store.sqlite_store import get_engine

    _ensure_tables()
    with get_engine().begin() as conn:
        _insert_turn(
            conn,
            user_id=user_id or "system",
            conversation_id=conversation_id,
            raw_question=raw_question,
            effective_question=effective_question,
            answer=answer,
            citations=list(citations or []),
            paper_ids=list(paper_ids or []),
            trace=dict(trace or {}),
            resolution_source=resolution_source,
            created_at=datetime.utcnow().isoformat(),
        )


def recent_turns(
    *,
    user_id: str = "system",
    conversation_id: str,
    limit: int = 3,
) -> list[ConversationTurn]:
    if not conversation_id:
        return []
    from ..store.sqlite_store import get_engine

    _ensure_tables()
    _migrate_legacy_if_empty(user_id or "system", conversation_id)
    with get_engine().begin() as conn:
        rows = list(
            conn.execute(
                text(
                    "SELECT raw_question, effective_question, answer, citations_json, "
                    "paper_ids_json, trace_json, resolution_source, created_at "
                    "FROM conversation_turns "
                    "WHERE user_id = :u AND conversation_id = :c "
                    "ORDER BY id DESC LIMIT :n"
                ),
                {"u": user_id or "system", "c": conversation_id, "n": limit},
            )
        )
    return [
        ConversationTurn(
            raw_question=str(row[0] or ""),
            effective_question=str(row[1] or ""),
            answer=str(row[2] or ""),
            citations=_json_loads(row[3], []),
            paper_ids=_json_loads(row[4], []),
            trace=_json_loads(row[5], {}),
            resolution_source=str(row[6] or ""),
            created_at=str(row[7] or ""),
        )
        for row in reversed(rows)
    ]


def append_summary(
    *,
    user_id: str,
    conversation_id: str,
    session_summary: str,
    research_memory: dict[str, list[str]],
    n_turns: int,
) -> None:
    if not conversation_id:
        return
    from ..store.sqlite_store import get_engine

    _ensure_tables()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO conversation_summaries "
                "(user_id, conversation_id, session_summary, research_memory_json, n_turns, updated_at) "
                "VALUES (:u, :c, :s, :m, :n, :t) "
                "ON CONFLICT(user_id, conversation_id) DO UPDATE SET "
                "session_summary = excluded.session_summary, "
                "research_memory_json = excluded.research_memory_json, "
                "n_turns = excluded.n_turns, "
                "updated_at = excluded.updated_at"
            ),
            {
                "u": user_id or "system",
                "c": conversation_id,
                "s": session_summary,
                "m": json.dumps(research_memory, ensure_ascii=False),
                "n": int(n_turns),
                "t": datetime.utcnow().isoformat(),
            },
        )


def load_summary(*, user_id: str = "system", conversation_id: str) -> dict | None:
    if not conversation_id:
        return None
    from ..store.sqlite_store import get_engine

    _ensure_tables()
    with get_engine().begin() as conn:
        row = conn.execute(
            text(
                "SELECT session_summary, research_memory_json, n_turns, updated_at "
                "FROM conversation_summaries "
                "WHERE user_id = :u AND conversation_id = :c"
            ),
            {"u": user_id or "system", "c": conversation_id},
        ).fetchone()
    if not row:
        return None
    return {
        "session_summary": str(row[0] or ""),
        "research_memory": _json_loads(row[1], {}),
        "n_turns": int(row[2] or 0),
        "updated_at": str(row[3] or ""),
    }


__all__ = [
    "ConversationTurn",
    "append_summary",
    "append_turn",
    "load_summary",
    "recent_turns",
]
