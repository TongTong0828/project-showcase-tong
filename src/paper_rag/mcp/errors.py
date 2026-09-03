"""Stable MCP domain error mapping."""

from __future__ import annotations

import os
from typing import Any

from pydantic import ValidationError

ERROR_CODES = {
    "VALIDATION",
    "NOT_FOUND",
    "CONFLICT",
    "UNAVAILABLE",
    "TIMEOUT",
    "CANCELLED",
    "INTERNAL",
}


class McpToolError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"invalid MCP error code: {code}")
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details or {}


def validation_error(exc: ValidationError) -> McpToolError:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(item) for item in first.get("loc", ()))
    msg = first.get("msg", "invalid input")
    return McpToolError("VALIDATION", f"{loc}: {msg}" if loc else str(msg))


def map_exception(exc: Exception) -> McpToolError:
    if isinstance(exc, McpToolError):
        return exc
    if isinstance(exc, TimeoutError):
        return McpToolError("TIMEOUT", "operation timed out", retryable=True)
    if isinstance(exc, (FileNotFoundError, KeyError)):
        return McpToolError("NOT_FOUND", _safe_message(exc))
    if isinstance(exc, ValueError):
        return McpToolError("VALIDATION", _safe_message(exc))
    return McpToolError("INTERNAL", _safe_message(exc))


def _safe_message(exc: Exception) -> str:
    message = str(exc) or type(exc).__name__
    message = _redact_secrets(message)
    return message.splitlines()[0][:500]


def _redact_secrets(text: str) -> str:
    redacted = text
    for key, value in os.environ.items():
        key_upper = key.upper()
        if not any(marker in key_upper for marker in ("KEY", "TOKEN", "SECRET")):
            continue
        if isinstance(value, str) and len(value) >= 8:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted
