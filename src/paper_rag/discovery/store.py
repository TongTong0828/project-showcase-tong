"""SQLite persistence for Paper Discovery Loop runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import config as cfg


def create_run(user_id: str, topic: str, sources: list[str], max_candidates: int) -> int:
    con = _connect()
    try:
        now = _now()
        cur = con.execute(
            """
            INSERT INTO discovery_runs
                (user_id, topic, sources_json, max_candidates, status, stopped_by,
                 trace_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'running', 'running', '{}', ?, ?)
            """,
            (user_id, topic, json.dumps(sources), max_candidates, now, now),
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def finish_run(run_id: int, *, status: str, stopped_by: str, trace: dict[str, Any]) -> None:
    con = _connect()
    try:
        con.execute(
            """
            UPDATE discovery_runs
            SET status = ?, stopped_by = ?, trace_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, stopped_by, json.dumps(trace, ensure_ascii=False), _now(), run_id),
        )
        con.commit()
    finally:
        con.close()


def save_candidates(run_id: int, candidates: list[dict[str, Any]]) -> list[int]:
    con = _connect()
    try:
        now = _now()
        ids: list[int] = []
        for candidate in candidates:
            cur = con.execute(
                """
                INSERT INTO discovery_candidates
                    (run_id, source, paper_id, title, abstract, authors_json, year,
                     doi, arxiv_id, urls_json, score, rank, selected, rank_reason,
                     skip_reason, ingest_status, ingest_result_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    candidate.get("source"),
                    candidate.get("paper_id"),
                    candidate.get("title"),
                    candidate.get("abstract"),
                    json.dumps(candidate.get("authors") or [], ensure_ascii=False),
                    candidate.get("year"),
                    candidate.get("doi"),
                    candidate.get("arxiv_id"),
                    json.dumps(candidate.get("urls") or [], ensure_ascii=False),
                    float(candidate.get("score") or 0.0),
                    candidate.get("rank"),
                    1 if candidate.get("selected") else 0,
                    candidate.get("rank_reason"),
                    candidate.get("skip_reason"),
                    candidate.get("ingest_status") or "pending",
                    candidate.get("ingest_result_json"),
                    now,
                    now,
                ),
            )
            ids.append(int(cur.lastrowid))
        con.commit()
        return ids
    finally:
        con.close()


def list_runs(user_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT *
            FROM discovery_runs
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [_run_row(row) for row in rows]
    finally:
        con.close()


def get_run(run_id: int, *, user_id: str | None = None) -> dict[str, Any]:
    con = _connect()
    try:
        if user_id is None:
            row = con.execute("SELECT * FROM discovery_runs WHERE id = ?", (run_id,)).fetchone()
        else:
            row = con.execute(
                "SELECT * FROM discovery_runs WHERE id = ? AND user_id = ?",
                (run_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"discovery run not found: {run_id}")
        candidates = con.execute(
            "SELECT * FROM discovery_candidates WHERE run_id = ? ORDER BY rank ASC, id ASC",
            (run_id,),
        ).fetchall()
        return {
            "run": _run_row(row),
            "trace": _json(row["trace_json"], {}),
            "candidates": [_candidate_row(candidate) for candidate in candidates],
        }
    finally:
        con.close()


def get_candidate(candidate_id: int, *, user_id: str | None = None) -> dict[str, Any]:
    con = _connect()
    try:
        query = """
            SELECT c.*, r.user_id
            FROM discovery_candidates c
            JOIN discovery_runs r ON r.id = c.run_id
            WHERE c.id = ?
        """
        params: tuple[Any, ...] = (candidate_id,)
        if user_id is not None:
            query += " AND r.user_id = ?"
            params = (candidate_id, user_id)
        row = con.execute(query, params).fetchone()
        if row is None:
            raise KeyError(f"discovery candidate not found: {candidate_id}")
        return _candidate_row(row)
    finally:
        con.close()


def update_candidate_ingest(candidate_id: int, *, status: str, result: dict[str, Any]) -> None:
    con = _connect()
    try:
        con.execute(
            """
            UPDATE discovery_candidates
            SET ingest_status = ?, ingest_result_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, json.dumps(result, ensure_ascii=False), _now(), candidate_id),
        )
        con.commit()
    finally:
        con.close()


def existing_paper_keys() -> set[str]:
    con = _connect()
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        papers_table = "paper" if "paper" in tables else "papers"
        if papers_table not in tables:
            return set()
        rows = con.execute(f"SELECT paper_id, arxiv_id, doi FROM {papers_table}").fetchall()
        keys: set[str] = set()
        for row in rows:
            for value in (row["paper_id"], row["arxiv_id"], row["doi"]):
                if value:
                    keys.add(str(value))
            if row["arxiv_id"]:
                keys.add(f"arxiv:{row['arxiv_id']}")
            if row["doi"]:
                keys.add(f"doi:{row['doi']}")
        return keys
    finally:
        con.close()


def _connect() -> sqlite3.Connection:
    path = Path(cfg.load().paths.sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    _ensure_schema(con)
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            sources_json TEXT NOT NULL,
            max_candidates INTEGER NOT NULL,
            status TEXT NOT NULL,
            stopped_by TEXT NOT NULL,
            trace_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            paper_id TEXT,
            title TEXT,
            abstract TEXT,
            authors_json TEXT NOT NULL DEFAULT '[]',
            year INTEGER,
            doi TEXT,
            arxiv_id TEXT,
            urls_json TEXT NOT NULL DEFAULT '[]',
            score REAL NOT NULL DEFAULT 0,
            rank INTEGER,
            selected INTEGER NOT NULL DEFAULT 0,
            rank_reason TEXT,
            skip_reason TEXT,
            ingest_status TEXT NOT NULL DEFAULT 'pending',
            ingest_result_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES discovery_runs(id)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_discovery_runs_user ON discovery_runs(user_id, id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_discovery_candidates_run ON discovery_candidates(run_id, rank)")
    con.commit()


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "topic": row["topic"],
        "sources": _json(row["sources_json"], []),
        "max_candidates": row["max_candidates"],
        "status": row["status"],
        "stopped_by": row["stopped_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _candidate_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "source": row["source"],
        "paper_id": row["paper_id"],
        "title": row["title"],
        "abstract": row["abstract"],
        "authors": _json(row["authors_json"], []),
        "year": row["year"],
        "doi": row["doi"],
        "arxiv_id": row["arxiv_id"],
        "urls": _json(row["urls_json"], []),
        "score": row["score"],
        "rank": row["rank"],
        "selected": bool(row["selected"]),
        "rank_reason": row["rank_reason"],
        "skip_reason": row["skip_reason"],
        "ingest_status": row["ingest_status"],
        "ingest_result_json": row["ingest_result_json"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"
