"""Lightweight question-answer cache.

Why: same question asked twice within a short window is common in research
(user re-runs a query to copy-paste). A 24h cache keyed on the resolved,
tenant-scoped query saves both LLM tokens and wall time.

Backed by SQLite. Lazy table creation. Cache key = sha1(normalized_question
+ user_id + sorted_paper_ids). Stored value = JSON of `qa_agentic.answer`
output plus chunk ids/fingerprints so hits can rehydrate evidence chunks.

Disabled by default; enable via `rag.qa_cache.enabled: true`.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta

from .. import config as cfg
from ..utils.logger import get_logger

log = get_logger("rag.qa_cache")
_TABLE_READY = False
_TABLE_ENGINE_KEY: int | None = None


def _norm_question(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _make_key(
    question: str,
    paper_ids: list[str] | None,
    *,
    user_id: str = "system",
) -> str:
    base = "|".join(
        [
            f"user:{user_id or 'system'}",
            f"question:{_norm_question(question)}",
            f"papers:{','.join(sorted(paper_ids or []))}",
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _ensure_table() -> None:
    from ..store.sqlite_store import get_engine

    engine = get_engine()
    global _TABLE_READY, _TABLE_ENGINE_KEY
    engine_key = id(engine)
    if _TABLE_READY and _TABLE_ENGINE_KEY == engine_key:
        return
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS qa_cache (
                key TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                paper_ids TEXT NOT NULL,
                answer_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
    _TABLE_READY = True
    _TABLE_ENGINE_KEY = engine_key


def _fingerprint_chunks(chunks: list[dict]) -> str:
    parts = [
        f"{chunk.get('chunk_id')}:{chunk.get('paper_id')}:{chunk.get('text') or ''}"
        for chunk in chunks
        if chunk.get("chunk_id")
    ]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _chunk_to_dict(chunk) -> dict:
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump()
    if hasattr(chunk, "dict"):
        return chunk.dict()
    return dict(chunk)


def _rehydrate_chunks(chunk_ids: list[str]) -> list[dict] | None:
    from ..store import sqlite_store

    chunks: list[dict] = []
    for chunk_id in chunk_ids:
        chunk = sqlite_store.get_chunk(chunk_id)
        if chunk is None:
            return None
        chunks.append(_chunk_to_dict(chunk))
    return chunks


def get(
    question: str,
    paper_ids: list[str] | None,
    *,
    user_id: str = "system",
) -> dict | None:
    if not _enabled():
        return None
    _ensure_table()
    from sqlalchemy import text

    from ..store.sqlite_store import get_engine

    key = _make_key(question, paper_ids, user_id=user_id)
    with get_engine().begin() as conn:
        row = conn.execute(
            text("SELECT answer_json, created_at FROM qa_cache WHERE key = :k"),
            {"k": key},
        ).first()
    if not row:
        return None
    answer_json, created_at = row
    age = datetime.utcnow() - datetime.fromisoformat(created_at)
    ttl = timedelta(hours=cfg.load().rag.qa_cache_ttl_hours)
    if age > ttl:
        log.info(f"qa_cache stale ({age}); evicting")
        _evict(key)
        return None
    log.info(f"qa_cache HIT (age={age})")
    payload = json.loads(answer_json)
    chunk_ids = [str(value) for value in payload.get("chunk_ids", []) if value]
    if chunk_ids:
        chunks = _rehydrate_chunks(chunk_ids)
        if chunks is None:
            log.info("qa_cache stale; cached chunks are no longer available")
            _evict(key)
            return None
        stored_fingerprint = payload.get("chunk_fingerprint") or ""
        if stored_fingerprint and _fingerprint_chunks(chunks) != stored_fingerprint:
            log.info("qa_cache stale; cached chunks changed")
            _evict(key)
            return None
        if not stored_fingerprint:
            log.info("qa_cache stale; missing cached chunk fingerprint")
            _evict(key)
            return None
        payload["chunks"] = chunks
    else:
        payload["chunks"] = []
    return payload


def put(
    question: str,
    paper_ids: list[str] | None,
    answer: dict,
    *,
    user_id: str = "system",
) -> None:
    if not _enabled():
        return
    _ensure_table()
    from sqlalchemy import text

    from ..store.sqlite_store import get_engine

    key = _make_key(question, paper_ids, user_id=user_id)
    chunks = answer.get("chunks") or []
    payload = {
        "answer": answer.get("answer"),
        "citations": answer.get("citations", []),
        "chunk_ids": [c.get("chunk_id") for c in chunks if c.get("chunk_id")],
        "chunk_fingerprint": _fingerprint_chunks(chunks),
        "trace": answer.get("trace"),
        "suspicious_citations": answer.get("suspicious_citations"),
    }
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT OR REPLACE INTO qa_cache (key, question, paper_ids, answer_json, created_at) "
                "VALUES (:k, :q, :p, :a, :t)"
            ),
            {
                "k": key,
                "q": question,
                "p": ",".join(sorted(paper_ids or [])),
                "a": json.dumps(payload, ensure_ascii=False),
                "t": datetime.utcnow().isoformat(),
            },
        )


def _evict(key: str) -> None:
    from sqlalchemy import text

    from ..store.sqlite_store import get_engine

    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM qa_cache WHERE key = :k"), {"k": key})


def _enabled() -> bool:
    return cfg.load().rag.qa_cache_enabled


__all__ = [
    "get",
    "put",
]
