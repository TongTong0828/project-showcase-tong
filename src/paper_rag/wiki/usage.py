"""Wiki consumption events for product traces and Knowledge Builder status."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..store.sqlite_store import get_engine
from ..utils.logger import get_logger

log = get_logger("wiki.usage")


def _ensure_schema() -> None:
    with get_engine().begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS wiki_consumption_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT,
                paper_id TEXT NOT NULL DEFAULT '',
                entry_id TEXT NOT NULL,
                entry_name TEXT NOT NULL DEFAULT '',
                wiki_fingerprint TEXT NOT NULL DEFAULT '',
                question TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_wiki_usage_paper "
            "ON wiki_consumption_events(paper_id, created_at)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_wiki_usage_trace "
            "ON wiki_consumption_events(trace_id)"
        )


def _paper_ids_for_context(
    paper_ids: list[str] | None,
    wiki_context: dict[str, Any],
) -> list[str]:
    explicit = [str(pid) for pid in (paper_ids or []) if pid]
    if explicit:
        return explicit
    out: list[str] = []
    for entry in wiki_context.get("entries") or []:
        for paper_id in entry.get("key_papers") or []:
            if paper_id:
                out.append(str(paper_id))
    return list(dict.fromkeys(out))


def record_consumption(
    *,
    question: str,
    paper_ids: list[str] | None,
    wiki_context: dict[str, Any],
    trace_id: str | None,
) -> None:
    entries = list((wiki_context or {}).get("entries") or [])
    if not entries:
        return
    papers = _paper_ids_for_context(paper_ids, wiki_context)
    if not papers:
        papers = [""]
    _ensure_schema()
    now = datetime.utcnow().isoformat()
    fingerprint = (wiki_context or {}).get("fingerprint", "")
    with get_engine().begin() as conn:
        for entry in entries:
            entry_id = entry.get("entry_id")
            if not entry_id:
                continue
            for paper_id in papers:
                conn.exec_driver_sql(
                    """
                    INSERT INTO wiki_consumption_events
                    (trace_id, paper_id, entry_id, entry_name, wiki_fingerprint,
                     question, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace_id,
                        paper_id,
                        str(entry_id),
                        str(entry.get("name") or ""),
                        fingerprint,
                        question,
                        now,
                    ),
                )
    log.info(f"wiki consumption recorded: trace={trace_id} entries={len(entries)}")


def consumed_paper_ids() -> set[str]:
    _ensure_schema()
    with get_engine().begin() as conn:
        rows = conn.exec_driver_sql(
            "SELECT DISTINCT paper_id FROM wiki_consumption_events WHERE paper_id != ''"
        ).fetchall()
    return {str(row[0]) for row in rows if row[0]}


__all__ = ["consumed_paper_ids", "record_consumption"]
