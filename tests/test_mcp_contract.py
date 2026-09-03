from __future__ import annotations

import json
import subprocess
import sys

import pytest

READONLY_TOOLS = [
    "paper_status",
    "paper_list",
    "paper_search",
    "paper_qa",
    "paper_section",
    "paper_compare",
    "wiki_lookup",
]


def test_readonly_toolset_lists_exact_g1_tools_with_output_schema():
    from paper_rag.mcp.context import McpServerConfig
    from paper_rag.mcp.registry import list_tools

    tools = list_tools(McpServerConfig(toolset="readonly"))

    assert [tool["name"] for tool in tools] == READONLY_TOOLS
    assert not any(tool["name"].startswith("mcp__") for tool in tools)
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"]["additionalProperties"] is False
        assert tool["outputSchema"]["type"] == "object"


def test_model_visible_schema_hides_authority_fields():
    from paper_rag.mcp.context import McpServerConfig
    from paper_rag.mcp.registry import list_tools

    forbidden = {
        "user_id",
        "actor_id",
        "conversation_id",
        "memory_mode",
        "context_source",
        "artifact_root",
        "import_root",
    }

    for tool in list_tools(McpServerConfig(toolset="full")):
        schema_text = json.dumps(tool["inputSchema"])
        assert forbidden.isdisjoint(schema_text.split('"'))


def test_domain_validation_returns_canonical_error_not_transport_error():
    from paper_rag.mcp.context import McpRequestContext, McpServerConfig
    from paper_rag.mcp.registry import call_tool

    result = call_tool(
        "paper_compare",
        {
            "paper_ids": ["p1", "p2", "p3", "p4", "p5"],
            "dimensions": ["method"],
        },
        McpRequestContext(config=McpServerConfig(toolset="readonly")),
    )

    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["ok"] is False
    assert structured["error"]["code"] == "VALIDATION"
    assert structured["error"]["retryable"] is False
    assert "[VALIDATION]" in result["content"][0]["text"]


def test_stdio_server_stdout_contains_only_jsonrpc_lines():
    request_lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "paper_rag.mcp"],
        input="\n".join(json.dumps(line) for line in request_lines) + "\n",
        text=True,
        capture_output=True,
        check=False,
        env={"PYTHONPATH": "src", **dict()},
    )

    assert proc.returncode == 0
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [line["id"] for line in lines] == [1, 2]
    assert lines[0]["result"]["capabilities"] == {"tools": {}}
    assert [tool["name"] for tool in lines[1]["result"]["tools"]] == READONLY_TOOLS


def test_core_import_does_not_require_harness_extra():
    import paper_rag

    assert paper_rag is not None
    with pytest.raises(ModuleNotFoundError):
        __import__("mcp")
