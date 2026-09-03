"""Persistent operation receipt API for idempotent write tools."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class ReceiptPayloadTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class BeginReceiptResult:
    status: str
    operation_id: str
    receipt_status: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class OperationReceiptStore:
    def __init__(self, path: str | Path, *, payload_limit_bytes: int = 64 * 1024) -> None:
        self.path = Path(path)
        self.payload_limit_bytes = payload_limit_bytes

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mcp_operation_receipts (
                    operation_id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    request_boundary_id TEXT NOT NULL,
                    tool_call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_operation_fingerprint
                ON mcp_operation_receipts(
                    conversation_id,
                    request_boundary_id,
                    tool_name,
                    args_sha256
                );

                CREATE INDEX IF NOT EXISTS idx_mcp_operation_actor_time
                ON mcp_operation_receipts(actor_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_mcp_operation_lookup
                ON mcp_operation_receipts(conversation_id, tool_name, args_sha256, updated_at);
                """
            )

    def begin(
        self,
        *,
        operation_id: str,
        actor_id: str,
        conversation_id: str,
        request_boundary_id: str,
        tool_call_id: str,
        tool_name: str,
        args_sha256: str,
    ) -> BeginReceiptResult:
        self.initialize()
        now = time.time()
        with sqlite3.connect(self.path) as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO mcp_operation_receipts
                    (operation_id, actor_id, conversation_id, request_boundary_id,
                     tool_call_id, tool_name, args_sha256, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
                    """,
                    (
                        operation_id,
                        actor_id,
                        conversation_id,
                        request_boundary_id,
                        tool_call_id,
                        tool_name,
                        args_sha256,
                        now,
                        now,
                    ),
                )
                conn.commit()
                return BeginReceiptResult("created", operation_id, "running")
            except sqlite3.IntegrityError:
                row = conn.execute(
                    """
                    SELECT operation_id, status, result_json, error_json
                    FROM mcp_operation_receipts
                    WHERE operation_id = ?
                       OR (conversation_id = ? AND request_boundary_id = ?
                           AND tool_name = ? AND args_sha256 = ?)
                    ORDER BY CASE WHEN operation_id = ? THEN 0 ELSE 1 END, updated_at DESC
                    LIMIT 1
                    """,
                    (
                        operation_id,
                        conversation_id,
                        request_boundary_id,
                        tool_name,
                        args_sha256,
                        operation_id,
                    ),
                ).fetchone()
        if row is None:
            raise
        existing_id, receipt_status, result_json, error_json = row
        status = "cached" if receipt_status in TERMINAL_STATUSES else "conflict"
        return BeginReceiptResult(
            status=status,
            operation_id=existing_id,
            receipt_status=receipt_status,
            result=_loads(result_json),
            error=_loads(error_json),
        )

    def finish_success(self, operation_id: str, result: dict[str, Any]) -> None:
        self._finish(operation_id, "succeeded", result_json=self._bounded_json(result))

    def finish_error(self, operation_id: str, status: str, error: dict[str, Any]) -> None:
        if status not in {"failed", "cancelled", "outcome_unknown"}:
            raise ValueError(f"invalid receipt error status: {status}")
        self._finish(operation_id, status, error_json=self._bounded_json(error))

    def mark_running_outcome_unknown(self, *, started_before: float) -> int:
        self.initialize()
        now = time.time()
        with sqlite3.connect(self.path) as conn:
            cur = conn.execute(
                """
                UPDATE mcp_operation_receipts
                SET status = 'outcome_unknown', updated_at = ?
                WHERE status = 'running' AND created_at < ?
                """,
                (now, started_before),
            )
            conn.commit()
            return int(cur.rowcount)

    def _finish(
        self,
        operation_id: str,
        status: str,
        *,
        result_json: str | None = None,
        error_json: str | None = None,
    ) -> None:
        self.initialize()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                UPDATE mcp_operation_receipts
                SET status = ?, result_json = COALESCE(?, result_json),
                    error_json = COALESCE(?, error_json), updated_at = ?
                WHERE operation_id = ?
                """,
                (status, result_json, error_json, time.time(), operation_id),
            )
            conn.commit()

    def _bounded_json(self, payload: dict[str, Any]) -> str:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(text.encode("utf-8")) > self.payload_limit_bytes:
            raise ReceiptPayloadTooLarge(
                f"receipt payload exceeds {self.payload_limit_bytes} bytes"
            )
        return text


def _loads(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value else None
