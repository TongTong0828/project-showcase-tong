from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class WorkspaceStore:
    """Local Workbench research-state store, separate from the Paper RAG corpus."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        project_id = _new_id("project")
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO projects
                    (project_id, name, description, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (project_id, name.strip(), description.strip(), now, now),
            )
        project = self.get_project(project_id)
        if project is None:
            raise RuntimeError("created project could not be loaded")
        return project

    def list_projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE status = 'active'"
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT project_id, name, description, status, created_at, updated_at
                FROM projects
                {where}
                ORDER BY updated_at DESC, created_at DESC
                """
            ).fetchall()
        return [_project_from_row(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT project_id, name, description, status, created_at, updated_at
                FROM projects
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
        return _project_from_row(row) if row else None

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        project = self._require_project(project_id)
        next_name = project["name"] if name is None else name.strip()
        next_description = project["description"] if description is None else description.strip()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE projects
                SET name = ?, description = ?, updated_at = ?
                WHERE project_id = ?
                """,
                (next_name, next_description, _now(), project_id),
            )
        return self._require_project(project_id)

    def archive_project(self, project_id: str) -> dict[str, Any]:
        self._require_project(project_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE projects
                SET status = 'archived', updated_at = ?
                WHERE project_id = ?
                """,
                (_now(), project_id),
            )
        return self._require_project(project_id)

    def add_project_paper(
        self,
        project_id: str,
        paper_id: str,
        title_snapshot: str = "",
        source: str = "manual",
    ) -> dict[str, Any]:
        self._require_project(project_id)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_papers
                    (project_id, paper_id, title_snapshot, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, paper_id)
                DO UPDATE SET
                    title_snapshot = excluded.title_snapshot,
                    source = excluded.source
                """,
                (project_id, paper_id, title_snapshot, source, now),
            )
            self._touch_project(conn, project_id)
            row = conn.execute(
                """
                SELECT project_id, paper_id, title_snapshot, source, created_at
                FROM project_papers
                WHERE project_id = ? AND paper_id = ?
                """,
                (project_id, paper_id),
            ).fetchone()
        return _paper_from_row(row)

    def pin_evidence(
        self,
        project_id: str,
        chunk_id: str,
        paper_id: str,
        quote_snapshot: str = "",
        source: str = "manual",
        score_snapshot: float | None = None,
        label: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        self._require_project(project_id)
        now = _now()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT pin_id FROM evidence_pins
                WHERE project_id = ? AND chunk_id = ?
                """,
                (project_id, chunk_id),
            ).fetchone()
            pin_id = existing["pin_id"] if existing else _new_id("pin")
            conn.execute(
                """
                INSERT INTO evidence_pins
                    (
                        pin_id, project_id, chunk_id, paper_id, label, note, source,
                        score_snapshot, quote_snapshot, created_at, updated_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, chunk_id)
                DO UPDATE SET
                    paper_id = excluded.paper_id,
                    label = excluded.label,
                    note = excluded.note,
                    source = excluded.source,
                    score_snapshot = excluded.score_snapshot,
                    quote_snapshot = excluded.quote_snapshot,
                    updated_at = excluded.updated_at
                """,
                (
                    pin_id,
                    project_id,
                    chunk_id,
                    paper_id,
                    label,
                    note,
                    source,
                    score_snapshot,
                    quote_snapshot,
                    now,
                    now,
                ),
            )
            self._touch_project(conn, project_id)
            row = conn.execute(
                """
                SELECT pin_id, project_id, chunk_id, paper_id, label, note, source,
                       score_snapshot, quote_snapshot, created_at, updated_at
                FROM evidence_pins
                WHERE project_id = ? AND chunk_id = ?
                """,
                (project_id, chunk_id),
            ).fetchone()
        return _pin_from_row(row)

    def upsert_note(
        self,
        project_id: str,
        target_type: str,
        target_id: str,
        body: str,
        note_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_project(project_id)
        _validate_target_type(target_type)
        now = _now()
        note_id = note_id or _new_id("note")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT project_id FROM notes WHERE note_id = ?",
                (note_id,),
            ).fetchone()
            if existing is not None and existing["project_id"] != project_id:
                raise ValueError(f"Note {note_id} does not belong to project {project_id}")
            conn.execute(
                """
                INSERT INTO notes
                    (note_id, project_id, target_type, target_id, body, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(note_id)
                DO UPDATE SET
                    target_type = excluded.target_type,
                    target_id = excluded.target_id,
                    body = excluded.body,
                    updated_at = excluded.updated_at
                """,
                (note_id, project_id, target_type, target_id, body, now, now),
            )
            self._touch_project(conn, project_id)
            row = conn.execute(
                """
                SELECT note_id, project_id, target_type, target_id, body, created_at, updated_at
                FROM notes
                WHERE project_id = ? AND note_id = ?
                """,
                (project_id, note_id),
            ).fetchone()
        return _note_from_row(row)

    def save_question(
        self,
        project_id: str,
        question: str,
        answer: str,
        citations: list[str],
        chunk_ids: list[str],
        trace_id: str | None = None,
        abstain: object | None = None,
        context_policy: object | None = None,
        citation_papers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self._require_project(project_id)
        question_id = _new_id("question")
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO saved_questions
                    (
                        question_id, project_id, question, answer, citations_json,
                        chunk_ids_json, trace_id, abstain_json, context_policy_json,
                        citation_papers_json, created_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question_id,
                    project_id,
                    question,
                    answer,
                    _json_dumps(citations),
                    _json_dumps(chunk_ids),
                    trace_id,
                    _json_dumps(abstain),
                    _json_dumps(context_policy),
                    _json_dumps(citation_papers or {}),
                    now,
                ),
            )
            self._touch_project(conn, project_id)
            row = conn.execute(
                """
                SELECT question_id, project_id, question, answer, citations_json,
                       chunk_ids_json, trace_id, abstain_json, context_policy_json,
                       citation_papers_json, created_at
                FROM saved_questions
                WHERE question_id = ?
                """,
                (question_id,),
            ).fetchone()
        return _question_from_row(row)

    def build_project_snapshot(self, project_id: str) -> dict[str, Any]:
        project = self._require_project(project_id)
        with self._connect() as conn:
            papers = [
                _paper_from_row(row)
                for row in conn.execute(
                    """
                    SELECT project_id, paper_id, title_snapshot, source, created_at
                    FROM project_papers
                    WHERE project_id = ?
                    ORDER BY created_at DESC, paper_id ASC
                    """,
                    (project_id,),
                ).fetchall()
            ]
            evidence = [
                _pin_from_row(row)
                for row in conn.execute(
                    """
                    SELECT pin_id, project_id, chunk_id, paper_id, label, note, source,
                           score_snapshot, quote_snapshot, created_at, updated_at
                    FROM evidence_pins
                    WHERE project_id = ?
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (project_id,),
                ).fetchall()
            ]
            notes = [
                _note_from_row(row)
                for row in conn.execute(
                    """
                    SELECT note_id, project_id, target_type, target_id, body, created_at, updated_at
                    FROM notes
                    WHERE project_id = ?
                    ORDER BY updated_at DESC
                    """,
                    (project_id,),
                ).fetchall()
            ]
            questions = [
                _question_from_row(row)
                for row in conn.execute(
                    """
                    SELECT question_id, project_id, question, answer, citations_json,
                           chunk_ids_json, trace_id, abstain_json, context_policy_json,
                           citation_papers_json, created_at
                    FROM saved_questions
                    WHERE project_id = ?
                    ORDER BY created_at DESC
                    """,
                    (project_id,),
                ).fetchall()
            ]
            compare_run_count = conn.execute(
                "SELECT COUNT(*) AS count FROM compare_runs WHERE project_id = ?",
                (project_id,),
            ).fetchone()["count"]
        return {
            "project": project,
            "summary": {
                "paper_count": len(papers),
                "evidence_count": len(evidence),
                "note_count": len(notes),
                "saved_question_count": len(questions),
                "compare_run_count": compare_run_count,
            },
            "papers": papers,
            "evidence": evidence,
            "notes": notes,
            "saved_questions": questions,
            "compare_runs": self.list_compare_runs(project_id),
            "warnings": [],
        }

    def create_dsh_handoff(self, project_id: str, instruction: str = "") -> dict[str, Any]:
        snapshot = self.build_project_snapshot(project_id)
        handoff_id = _new_id("handoff")
        prompt = _build_project_prompt(snapshot, instruction)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dsh_handoffs
                    (
                        handoff_id, project_id, prompt, paper_ids_json,
                        chunk_ids_json, question_ids_json, created_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handoff_id,
                    project_id,
                    prompt,
                    _json_dumps([paper["paper_id"] for paper in snapshot["papers"]]),
                    _json_dumps([pin["chunk_id"] for pin in snapshot["evidence"]]),
                    _json_dumps(
                        [question["question_id"] for question in snapshot["saved_questions"]]
                    ),
                    now,
                ),
            )
            self._touch_project(conn, project_id)
        return {
            "handoff_id": handoff_id,
            "project_id": project_id,
            "prompt": prompt,
            "paper_ids": [paper["paper_id"] for paper in snapshot["papers"]],
            "chunk_ids": [pin["chunk_id"] for pin in snapshot["evidence"]],
            "question_ids": [
                question["question_id"] for question in snapshot["saved_questions"]
            ],
            "created_at": now,
        }

    def create_compare_run(
        self,
        project_id: str,
        paper_ids: list[str],
        dimensions: list[str],
    ) -> dict[str, Any]:
        self._require_project(project_id)
        selected_paper_ids = paper_ids or [
            paper["paper_id"] for paper in self.build_project_snapshot(project_id)["papers"]
        ]
        project_paper_ids = {
            paper["paper_id"] for paper in self.build_project_snapshot(project_id)["papers"]
        }
        unknown_paper_ids = [
            paper_id for paper_id in selected_paper_ids if paper_id not in project_paper_ids
        ]
        if unknown_paper_ids:
            raise ValueError(f"Papers not in project: {', '.join(unknown_paper_ids)}")
        selected_dimensions = dimensions or ["method", "limitation"]
        run_id = _new_id("compare")
        now = _now()
        warnings = ["LLM synthesis unavailable; rendered evidence-only matrix."]
        cells = self._build_compare_cells(
            project_id,
            selected_paper_ids,
            selected_dimensions,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO compare_runs
                    (
                        run_id, project_id, dimensions_json, paper_ids_json,
                        status, warnings_json, created_at
                    )
                VALUES (?, ?, ?, ?, 'degraded', ?, ?)
                """,
                (
                    run_id,
                    project_id,
                    _json_dumps(selected_dimensions),
                    _json_dumps(selected_paper_ids),
                    _json_dumps(warnings),
                    now,
                ),
            )
            for cell in cells:
                conn.execute(
                    """
                    INSERT INTO compare_cells
                        (
                            cell_id, run_id, project_id, paper_id, dimension, summary,
                            evidence_chunk_ids_json, note_ids_json, confidence
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("cell"),
                        run_id,
                        project_id,
                        cell["paper_id"],
                        cell["dimension"],
                        cell["summary"],
                        _json_dumps(cell["evidence_chunk_ids"]),
                        _json_dumps(cell["note_ids"]),
                        cell["confidence"],
                    ),
                )
            self._touch_project(conn, project_id)
        run = self.get_compare_run(project_id, run_id)
        if run is None:
            raise RuntimeError("created compare run could not be loaded")
        return run

    def list_compare_runs(self, project_id: str) -> list[dict[str, Any]]:
        self._require_project(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id
                FROM compare_runs
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [
            run
            for row in rows
            if (run := self.get_compare_run(project_id, row["run_id"])) is not None
        ]

    def get_compare_run(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        self._require_project(project_id)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, project_id, dimensions_json, paper_ids_json,
                       status, warnings_json, created_at
                FROM compare_runs
                WHERE project_id = ? AND run_id = ?
                """,
                (project_id, run_id),
            ).fetchone()
            if row is None:
                return None
            cell_rows = conn.execute(
                """
                SELECT paper_id, dimension, summary, evidence_chunk_ids_json,
                       note_ids_json, confidence
                FROM compare_cells
                WHERE project_id = ? AND run_id = ?
                ORDER BY rowid ASC
                """,
                (project_id, run_id),
            ).fetchall()
        return {
            "run_id": row["run_id"],
            "project_id": row["project_id"],
            "dimensions": _json_loads(row["dimensions_json"], []),
            "paper_ids": _json_loads(row["paper_ids_json"], []),
            "status": row["status"],
            "cells": [_compare_cell_from_row(cell_row) for cell_row in cell_rows],
            "warnings": _json_loads(row["warnings_json"], []),
            "created_at": row["created_at"],
        }

    def create_compare_dsh_handoff(self, project_id: str, run_id: str) -> dict[str, Any]:
        run = self.get_compare_run(project_id, run_id)
        if run is None:
            raise KeyError(f"Compare run not found: {run_id}")
        prompt = _build_compare_prompt(run)
        return {
            "handoff_id": _new_id("handoff"),
            "project_id": project_id,
            "prompt": prompt,
            "paper_ids": run["paper_ids"],
            "chunk_ids": sorted(
                {
                    chunk_id
                    for cell in run["cells"]
                    for chunk_id in cell["evidence_chunk_ids"]
                }
            ),
            "question_ids": [],
            "created_at": _now(),
        }

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_papers (
                    project_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    title_snapshot TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, paper_id),
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );

                CREATE TABLE IF NOT EXISTS evidence_pins (
                    pin_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    score_snapshot REAL,
                    quote_snapshot TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (project_id, chunk_id),
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );

                CREATE TABLE IF NOT EXISTS notes (
                    note_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );

                CREATE TABLE IF NOT EXISTS saved_questions (
                    question_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    chunk_ids_json TEXT NOT NULL,
                    trace_id TEXT,
                    abstain_json TEXT,
                    context_policy_json TEXT,
                    citation_papers_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );

                CREATE TABLE IF NOT EXISTS dsh_handoffs (
                    handoff_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    paper_ids_json TEXT NOT NULL,
                    chunk_ids_json TEXT NOT NULL,
                    question_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );

                CREATE TABLE IF NOT EXISTS compare_runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    dimensions_json TEXT NOT NULL,
                    paper_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );

                CREATE TABLE IF NOT EXISTS compare_cells (
                    cell_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    dimension TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence_chunk_ids_json TEXT NOT NULL,
                    note_ids_json TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES compare_runs(run_id),
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );
                """
            )
            _ensure_column(
                conn,
                "saved_questions",
                "citation_papers_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _build_compare_cells(
        self,
        project_id: str,
        paper_ids: list[str],
        dimensions: list[str],
    ) -> list[dict[str, Any]]:
        snapshot = self.build_project_snapshot(project_id)
        evidence_by_paper: dict[str, list[dict[str, Any]]] = {}
        for pin in snapshot["evidence"]:
            evidence_by_paper.setdefault(pin["paper_id"], []).append(pin)

        saved_citations_by_paper: dict[str, list[str]] = {}
        selected_paper_ids = set(paper_ids)
        for question in snapshot["saved_questions"]:
            citation_papers = question.get("citation_papers") or {}
            for chunk_id in question.get("chunk_ids") or question.get("citations") or []:
                paper_id = citation_papers.get(chunk_id)
                if paper_id in selected_paper_ids:
                    saved_citations_by_paper.setdefault(paper_id, []).append(chunk_id)

        notes_by_paper: dict[str, list[dict[str, Any]]] = {}
        notes_by_chunk: dict[str, list[dict[str, Any]]] = {}
        for note in snapshot["notes"]:
            if note["target_type"] == "paper":
                notes_by_paper.setdefault(note["target_id"], []).append(note)
            if note["target_type"] == "chunk":
                notes_by_chunk.setdefault(note["target_id"], []).append(note)

        cells: list[dict[str, Any]] = []
        for paper_id in paper_ids:
            pins = evidence_by_paper.get(paper_id, [])
            chunk_ids = _dedupe_preserve_order(
                [pin["chunk_id"] for pin in pins]
                + saved_citations_by_paper.get(paper_id, [])
            )
            note_ids = [note["note_id"] for note in notes_by_paper.get(paper_id, [])]
            for chunk_id in chunk_ids:
                note_ids.extend(note["note_id"] for note in notes_by_chunk.get(chunk_id, []))

            for dimension in dimensions:
                if pins:
                    first_quote = pins[0].get("quote_snapshot") or pins[0]["chunk_id"]
                    summary = f"Evidence pinned for {dimension}: {first_quote}"
                    confidence = "evidence_backed"
                elif chunk_ids:
                    summary = f"Saved QA citation for {dimension}: {chunk_ids[0]}"
                    confidence = "partial"
                else:
                    summary = "No pinned evidence"
                    confidence = "missing"
                cells.append(
                    {
                        "paper_id": paper_id,
                        "dimension": dimension,
                        "summary": summary,
                        "evidence_chunk_ids": chunk_ids,
                        "note_ids": sorted(set(note_ids)),
                        "confidence": confidence,
                    }
                )
        return cells

    def _require_project(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        if project is None:
            raise KeyError(f"Project not found: {project_id}")
        return project

    @staticmethod
    def _touch_project(conn: sqlite3.Connection, project_id: str) -> None:
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE project_id = ?",
            (_now(), project_id),
        )


def _build_project_prompt(snapshot: dict[str, Any], instruction: str) -> str:
    project = snapshot["project"]
    papers = snapshot["papers"]
    evidence = snapshot["evidence"]
    notes = snapshot["notes"]
    questions = snapshot["saved_questions"]
    lines = [
        "基于 Paper RAG Workbench 当前项目继续研究。",
        "",
        f"项目: {project['name']}",
    ]
    if project.get("description"):
        lines.append(f"描述: {project['description']}")
    if instruction.strip():
        lines.extend(["", f"任务: {instruction.strip()}"])
    lines.extend(["", "论文:"])
    lines.extend(
        f"- {paper['paper_id']}: {paper.get('title_snapshot') or 'Untitled'}"
        for paper in papers
    )
    if not papers:
        lines.append("- 未选择论文")
    lines.extend(["", "证据:"])
    lines.extend(
        (
            f"- {pin['paper_id']} / {pin['chunk_id']}: "
            f"{pin.get('quote_snapshot') or 'No excerpt'}"
        )
        for pin in evidence
    )
    if not evidence:
        lines.append("- 未钉选证据")
    lines.extend(["", "笔记:"])
    lines.extend(
        f"- {note['target_type']}:{note['target_id']}: {note['body']}" for note in notes
    )
    if not notes:
        lines.append("- 无项目笔记")
    lines.extend(["", "已保存问题:"])
    lines.extend(
        f"- {question['question']} -> citations: {', '.join(question['citations']) or 'none'}"
        for question in questions
    )
    if not questions:
        lines.append("- 无已保存问题")
    lines.extend(["", "请使用 Paper RAG 工具核查关键结论，所有论文事实保留证据引用。"])
    return "\n".join(lines)


def _build_compare_prompt(run: dict[str, Any]) -> str:
    lines = [
        "Continue from this Paper RAG Workbench Compare run.",
        "",
        f"Compare run: {run['run_id']}",
        f"Project: {run['project_id']}",
        f"Dimensions: {', '.join(run['dimensions'])}",
        "",
        "Cells:",
    ]
    for cell in run["cells"]:
        evidence = ", ".join(cell["evidence_chunk_ids"]) or "No pinned evidence"
        lines.append(
            (
                f"- {cell['paper_id']} / {cell['dimension']}: "
                f"{cell['summary']} | evidence: {evidence}"
            )
        )
    lines.extend(
        [
            "",
            "Use Paper RAG tools to verify paper facts. Keep user notes separate from paper evidence.",
        ]
    )
    return "\n".join(lines)


def _project_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "project_id": row["project_id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _paper_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "project_id": row["project_id"],
        "paper_id": row["paper_id"],
        "title_snapshot": row["title_snapshot"],
        "source": row["source"],
        "created_at": row["created_at"],
    }


def _pin_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "pin_id": row["pin_id"],
        "project_id": row["project_id"],
        "chunk_id": row["chunk_id"],
        "paper_id": row["paper_id"],
        "label": row["label"],
        "note": row["note"],
        "source": row["source"],
        "score_snapshot": row["score_snapshot"],
        "quote_snapshot": row["quote_snapshot"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _note_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "note_id": row["note_id"],
        "project_id": row["project_id"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "body": row["body"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _question_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "question_id": row["question_id"],
        "project_id": row["project_id"],
        "question": row["question"],
        "answer": row["answer"],
        "citations": _json_loads(row["citations_json"], []),
        "chunk_ids": _json_loads(row["chunk_ids_json"], []),
        "trace_id": row["trace_id"],
        "abstain": _json_loads(row["abstain_json"], None),
        "context_policy": _json_loads(row["context_policy_json"], None),
        "citation_papers": _json_loads(row["citation_papers_json"], {}),
        "created_at": row["created_at"],
    }


def _compare_cell_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "paper_id": row["paper_id"],
        "dimension": row["dimension"],
        "summary": row["summary"],
        "evidence_chunk_ids": _json_loads(row["evidence_chunk_ids_json"], []),
        "note_ids": _json_loads(row["note_ids_json"], []),
        "confidence": row["confidence"],
    }


def _json_dumps(value: object | None) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_target_type(target_type: str) -> None:
    if target_type not in {"project", "paper", "chunk"}:
        raise ValueError(f"Unsupported note target_type: {target_type}")
