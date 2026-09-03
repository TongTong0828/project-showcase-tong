"""Lightweight wiki review queue for QA/feedback closed-loop signals."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from ..store.sqlite_store import get_engine
from ..utils.logger import get_logger
from .schema import normalize_name

log = get_logger("wiki.review_queue")

def _ensure_schema() -> None:
    with get_engine().begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS wiki_review_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                concept TEXT,
                concept_norm TEXT NOT NULL DEFAULT '',
                paper_id TEXT NOT NULL DEFAULT '',
                question TEXT,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_wiki_review_status "
            "ON wiki_review_queue(status, created_at)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_wiki_review_dedupe "
            "ON wiki_review_queue(event_type, concept_norm, paper_id, reason, created_at)"
        )


def _json(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def enqueue(
    event_type: str,
    *,
    concept: str | None = None,
    paper_id: str | None = None,
    question: str | None = None,
    reason: str = "",
    payload: dict[str, Any] | None = None,
) -> int | None:
    """Insert or dedupe a pending wiki review event.

    Duplicate means same event type, normalized concept, paper id, and reason
    in the previous 24 hours. The original row id is returned on dedupe.
    """
    if not event_type:
        return None
    _ensure_schema()
    now = datetime.utcnow()
    cutoff = (now - timedelta(hours=24)).isoformat()
    concept_norm = normalize_name(concept or "")
    paper = paper_id or ""
    reason = reason or ""
    with get_engine().begin() as conn:
        existing = conn.exec_driver_sql(
            """
            SELECT id FROM wiki_review_queue
            WHERE event_type = ?
              AND concept_norm = ?
              AND paper_id = ?
              AND reason = ?
              AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (event_type, concept_norm, paper, reason, cutoff),
        ).first()
        if existing:
            return int(existing[0])
        cur = conn.exec_driver_sql(
            """
            INSERT INTO wiki_review_queue
            (event_type, concept, concept_norm, paper_id, question, reason, status,
             payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                event_type,
                concept,
                concept_norm,
                paper,
                question,
                reason,
                _json(payload),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        rid = int(cur.lastrowid)
    log.info(f"wiki review queued: id={rid} type={event_type} reason={reason}")
    return rid


def count_pending() -> int:
    _ensure_schema()
    with get_engine().begin() as conn:
        row = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM wiki_review_queue WHERE status = 'pending'"
        ).first()
    return int(row[0] if row else 0)


def recent(limit: int = 20) -> list[dict[str, Any]]:
    _ensure_schema()
    limit = max(1, min(int(limit or 20), 100))
    with get_engine().begin() as conn:
        rows = conn.exec_driver_sql(
            """
            SELECT id, event_type, concept, paper_id, question, reason, status,
                   payload_json, created_at, updated_at
            FROM wiki_review_queue
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row[7] or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        out.append({
            "id": int(row[0]),
            "event_type": row[1],
            "concept": row[2],
            "paper_id": row[3] or None,
            "question": row[4],
            "reason": row[5],
            "status": row[6],
            "payload": payload,
            "created_at": row[8],
            "updated_at": row[9],
        })
    return out


__all__ = ["count_pending", "enqueue", "recent"]
