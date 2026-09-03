"""Minimal JSON-RPC stdio MCP server."""

from __future__ import annotations

import json
import sys
from typing import Any

from .context import McpRequestContext, McpServerConfig
from .registry import call_tool, list_tools


def handle_jsonrpc(message: dict[str, Any], config: McpServerConfig) -> dict[str, Any] | None:
    request_id = message.get("id")
    if request_id is None:
        return None

    method = message.get("method")
    try:
        if method == "initialize":
            params = message.get("params") or {}
            return _result(
                request_id,
                {
                    "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "paper-rag-mcp", "version": "0.1.0"},
                },
            )
        if method == "tools/list":
            return _result(request_id, {"tools": list_tools(config)})
        if method == "tools/call":
            params = message.get("params") or {}
            ctx = McpRequestContext.from_meta(config, params.get("_meta"))
            return _result(
                request_id,
                call_tool(str(params.get("name", "")), params.get("arguments") or {}, ctx),
            )
        if method == "ping":
            return _result(request_id, {})
        return _error(request_id, -32601, f"unsupported method: {method}")
    except Exception as exc:  # pragma: no cover - defensive framing guard
        return _error(request_id, -32603, str(exc).splitlines()[0][:500])


def run_stdio(config: McpServerConfig | None = None) -> int:
    config = config or McpServerConfig.from_env()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, str(exc))
        else:
            response = handle_jsonrpc(message, config)
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
