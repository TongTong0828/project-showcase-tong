from __future__ import annotations

import json
import sqlite3
import time


def test_operation_receipt_returns_cached_terminal_result_without_repeating(tmp_path):
    from paper_rag.mcp.operations import OperationReceiptStore

    store = OperationReceiptStore(tmp_path / "receipts.sqlite")
    created = store.begin(
        operation_id="op-1",
        actor_id="system",
        conversation_id="session-1",
        request_boundary_id="boundary-1",
        tool_call_id="call-1",
        tool_name="paper_ingest",
        args_sha256="abc",
    )
    store.finish_success("op-1", {"paper_id": "p1", "status": "ingested"})
    cached = store.begin(
        operation_id="op-1",
        actor_id="system",
        conversation_id="session-1",
        request_boundary_id="boundary-1",
        tool_call_id="call-2",
        tool_name="paper_ingest",
        args_sha256="abc",
    )

    assert created.status == "created"
    assert cached.status == "cached"
    assert cached.receipt_status == "succeeded"
    assert cached.result == {"paper_id": "p1", "status": "ingested"}


def test_operation_receipt_fingerprint_blocks_same_boundary_duplicate(tmp_path):
    from paper_rag.mcp.operations import OperationReceiptStore

    store = OperationReceiptStore(tmp_path / "receipts.sqlite")
    store.begin(
        operation_id="op-1",
        actor_id="system",
        conversation_id="session-1",
        request_boundary_id="boundary-1",
        tool_call_id="call-1",
        tool_name="paper_ingest",
        args_sha256="same",
    )
    duplicate = store.begin(
        operation_id="op-2",
        actor_id="system",
        conversation_id="session-1",
        request_boundary_id="boundary-1",
        tool_call_id="call-2",
        tool_name="paper_ingest",
        args_sha256="same",
    )

    assert duplicate.status == "conflict"
    assert duplicate.receipt_status == "running"
    assert duplicate.operation_id == "op-1"


def test_startup_marks_previous_running_receipts_outcome_unknown(tmp_path):
    from paper_rag.mcp.operations import OperationReceiptStore

    path = tmp_path / "receipts.sqlite"
    store = OperationReceiptStore(path)
    store.begin(
        operation_id="old-op",
        actor_id="system",
        conversation_id="session-1",
        request_boundary_id="boundary-1",
        tool_call_id="call-1",
        tool_name="paper_ingest",
        args_sha256="abc",
    )
    cutoff = time.time() + 1
    marked = store.mark_running_outcome_unknown(started_before=cutoff)

    with sqlite3.connect(path) as conn:
        status = conn.execute(
            "SELECT status FROM mcp_operation_receipts WHERE operation_id = ?",
            ("old-op",),
        ).fetchone()[0]

    assert marked == 1
    assert status == "outcome_unknown"


def test_receipt_payloads_are_bounded(tmp_path):
    from paper_rag.mcp.operations import OperationReceiptStore, ReceiptPayloadTooLarge

    store = OperationReceiptStore(tmp_path / "receipts.sqlite", payload_limit_bytes=64)
    store.begin(
        operation_id="op-1",
        actor_id="system",
        conversation_id="session-1",
        request_boundary_id="boundary-1",
        tool_call_id="call-1",
        tool_name="paper_deliver",
        args_sha256="abc",
    )

    try:
        store.finish_success("op-1", {"too_large": "x" * 200})
    except ReceiptPayloadTooLarge as exc:
        assert "64" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected bounded receipt payload")


def test_operation_table_ddl_matches_additive_plan(tmp_path):
    from paper_rag.mcp.operations import OperationReceiptStore

    path = tmp_path / "receipts.sqlite"
    OperationReceiptStore(path).initialize()

    with sqlite3.connect(path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(mcp_operation_receipts)").fetchall()
        }
        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(mcp_operation_receipts)").fetchall()
        }

    assert {
        "operation_id",
        "actor_id",
        "conversation_id",
        "request_boundary_id",
        "tool_call_id",
        "tool_name",
        "args_sha256",
        "status",
        "result_json",
        "error_json",
        "created_at",
        "updated_at",
    } <= columns
    assert {
        "idx_mcp_operation_fingerprint",
        "idx_mcp_operation_actor_time",
        "idx_mcp_operation_lookup",
    } <= indexes
