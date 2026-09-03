"""MCP structured result envelopes and bounded text projections."""

from __future__ import annotations

from typing import Any

MAX_MODEL_TEXT_BYTES = 1400
MAX_SNIPPET_CHARS = 360
MAX_SECTION_CHARS = 1200


def truncate_text(value: Any, limit: int = MAX_SNIPPET_CHARS) -> tuple[str, bool]:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text, False
    return text[: max(0, limit - 3)] + "...", True


def success_result(
    tool: str,
    data: dict[str, Any],
    *,
    evidence_role: str,
    trace_id: str | None = None,
    warnings: list[str] | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    envelope = {
        "ok": True,
        "tool": tool,
        "trace_id": trace_id,
        "data": data,
        "warnings": warnings or [],
        "evidence_role": evidence_role,
        "truncated": truncated,
    }
    return mcp_result(envelope)


def error_result(
    tool: str,
    *,
    code: str,
    message: str,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = {
        "ok": False,
        "tool": tool,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details or {},
        },
        "warnings": [],
        "evidence_role": "none",
        "truncated": False,
    }
    return mcp_result(envelope)


def mcp_result(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "isError": False,
        "content": [{"type": "text", "text": project_for_model(envelope)}],
        "structuredContent": envelope,
    }


def project_for_model(envelope: dict[str, Any]) -> str:
    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        return _bounded(
            f"[{error.get('code', 'INTERNAL')}] {error.get('message', 'tool failed')} "
            f"retryable={bool(error.get('retryable'))}"
        )

    data = envelope.get("data") or {}
    parts = [
        "ok=true",
        f"tool={envelope.get('tool')}",
        f"evidence_role={envelope.get('evidence_role')}",
    ]
    if envelope.get("trace_id"):
        parts.append(f"trace_id={envelope['trace_id']}")
    if envelope.get("truncated") or data.get("truncated"):
        parts.append("truncated=true")
    abstain = data.get("abstain")
    if abstain:
        decision = abstain.get("decision") if isinstance(abstain, dict) else abstain
        parts.append(f"abstain={decision}")
    citations = data.get("citations")
    if citations is not None:
        parts.append("citations=" + ",".join(str(item) for item in citations))
    if "count" in data:
        parts.append(f"count={data['count']}")
    if "papers" in data and isinstance(data["papers"], list):
        parts.append(f"papers={len(data['papers'])}")
    if "results" in data and isinstance(data["results"], list):
        parts.append(f"results={len(data['results'])}")
    return _bounded(" ".join(parts))


def bounded_chunks(chunks: list[dict[str, Any]], *, text_limit: int = MAX_SECTION_CHARS) -> tuple[list[dict[str, Any]], bool]:
    out: list[dict[str, Any]] = []
    truncated = False
    for chunk in chunks:
        item = dict(chunk)
        text, did_truncate = truncate_text(item.get("text", ""), text_limit)
        item["text"] = text
        truncated = truncated or did_truncate
        out.append(item)
    return out, truncated


def _bounded(text: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_MODEL_TEXT_BYTES:
        return text
    return encoded[: MAX_MODEL_TEXT_BYTES - 3].decode("utf-8", errors="ignore") + "..."
