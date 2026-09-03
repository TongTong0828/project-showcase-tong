from __future__ import annotations

from pathlib import Path


def _ctx(tmp_path: Path, *, actor: str = "alice", boundary: str | None = "boundary-1"):
    from paper_rag.mcp.context import McpRequestContext, McpServerConfig

    return McpRequestContext(
        config=McpServerConfig(
            toolset="full",
            actor_id=actor,
            artifact_root=tmp_path / "artifacts",
            import_root=tmp_path / "imports",
        ),
        conversation_id="dsh-session-1",
        tool_call_id="call-1",
        request_boundary_id=boundary,
    )


def test_subscription_tools_are_actor_scoped_and_boundary_gated(monkeypatch, tmp_path):
    monkeypatch.setenv("FEEDBACK_SQLITE_PATH", str(tmp_path / "feedback.sqlite"))
    from paper_rag.mcp.registry import call_tool

    denied = call_tool(
        "subscription_add",
        {"kind": "keyword", "value": "Self-RAG", "strength": "high"},
        _ctx(tmp_path, boundary=None),
    )["structuredContent"]
    added = call_tool(
        "subscription_add",
        {"kind": "keyword", "value": "Self-RAG", "strength": "high"},
        _ctx(tmp_path),
    )["structuredContent"]
    listed = call_tool("subscription_list", {}, _ctx(tmp_path, boundary=None))["structuredContent"]
    bob_listed = call_tool(
        "subscription_list", {}, _ctx(tmp_path, actor="bob", boundary=None)
    )["structuredContent"]
    toggled_by_bob = call_tool(
        "subscription_toggle",
        {"subscription_id": added["data"]["subscription_id"], "enabled": False},
        _ctx(tmp_path, actor="bob"),
    )["structuredContent"]
    deleted = call_tool(
        "subscription_delete",
        {"subscription_id": added["data"]["subscription_id"]},
        _ctx(tmp_path),
    )["structuredContent"]

    assert denied["error"]["code"] == "UNAVAILABLE"
    assert added["ok"] is True
    assert listed["data"]["count"] == 1
    assert listed["data"]["subscriptions"][0]["user_id"] == "alice"
    assert bob_listed["data"]["count"] == 0
    assert toggled_by_bob["data"]["updated"] is False
    assert deleted["data"]["deleted"] is True


def test_inbox_tools_are_actor_scoped_and_boundary_gated(monkeypatch, tmp_path):
    monkeypatch.setenv("FEEDBACK_SQLITE_PATH", str(tmp_path / "feedback.sqlite"))
    from paper_rag.mcp.registry import call_tool
    from paper_rag.proactive import inbox

    alice_id = inbox.write("alice", "daily_digest", "A", body_md="alpha")
    inbox.write("bob", "daily_digest", "B", body_md="beta")

    listed = call_tool(
        "inbox_list", {"unread_only": True, "limit": 10}, _ctx(tmp_path, boundary=None)
    )["structuredContent"]
    denied = call_tool(
        "inbox_mark_read", {"item_id": alice_id}, _ctx(tmp_path, boundary=None)
    )["structuredContent"]
    bob_mark = call_tool(
        "inbox_mark_read", {"item_id": alice_id}, _ctx(tmp_path, actor="bob")
    )["structuredContent"]
    marked = call_tool("inbox_mark_read", {"item_id": alice_id}, _ctx(tmp_path))[
        "structuredContent"
    ]
    dismissed = call_tool("inbox_dismiss", {"item_id": alice_id}, _ctx(tmp_path))[
        "structuredContent"
    ]

    assert listed["data"]["unread_count"] == 1
    assert [item["title"] for item in listed["data"]["items"]] == ["A"]
    assert denied["error"]["code"] == "UNAVAILABLE"
    assert bob_mark["data"]["updated"] is False
    assert marked["data"]["updated"] is True
    assert dismissed["data"]["dismissed"] is True


def test_feedback_record_strips_raw_comment_and_dedups(monkeypatch, tmp_path):
    monkeypatch.setenv("FEEDBACK_SQLITE_PATH", str(tmp_path / "feedback.sqlite"))
    from paper_rag.feedback import collector, recent_events
    from paper_rag.mcp.registry import call_tool

    collector._counter.clear()
    payload = {
        "event_type": "thumbs_down",
        "trace_id": "trace-1",
        "payload": {
            "reason": "hallucination",
            "comment": "This answer hallucinated a fake paper.",
        },
    }

    first = call_tool("feedback_record", payload, _ctx(tmp_path))["structuredContent"]
    second = call_tool("feedback_record", payload, _ctx(tmp_path))["structuredContent"]
    events = recent_events("alice", limit=10)

    assert first["ok"] is True
    assert first["data"]["event_id"] == second["data"]["event_id"]
    assert events[0]["payload"]["reason"] == "hallucination"
    assert "comment" not in events[0]["payload"]
    assert events[0]["payload"]["comment_length"] > 0


def test_digest_and_stale_tools_require_boundary_and_return_counts(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("FEEDBACK_SQLITE_PATH", str(tmp_path / "feedback.sqlite"))
    from paper_rag.mcp.registry import call_tool
    from paper_rag.proactive import digest, stale

    monkeypatch.setattr(digest, "daily_digest_for_user", lambda user_id, days=1: 123)
    monkeypatch.setattr(
        stale,
        "stale_scan_for_user",
        lambda user_id, older_than_days=30, max_cards=3: 2,
    )

    denied = call_tool("digest_run", {}, _ctx(tmp_path, boundary=None))["structuredContent"]
    digest_result = call_tool("digest_run", {"days": 3}, _ctx(tmp_path))[
        "structuredContent"
    ]
    stale_result = call_tool(
        "stale_scan", {"older_than_days": 45, "max_cards": 5}, _ctx(tmp_path)
    )["structuredContent"]

    assert denied["error"]["code"] == "UNAVAILABLE"
    assert digest_result["data"] == {"item_id": 123, "written": True}
    assert stale_result["data"] == {"count": 2}
