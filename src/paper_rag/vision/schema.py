"""Shared schema for visual chunk summarization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STATUS_OK = "ok"
STATUS_FALLBACK = "fallback"
STATUS_CACHED = "cached"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_UNAVAILABLE = "unavailable"
PROMPT_VERSION = "v1"


@dataclass(frozen=True)
class VisualSummaryRequest:
    paper_id: str
    chunk_id: str
    modality: str
    asset_path: Path
    caption: str = ""
    surrounding_context: str = ""
    model: str | None = None
    prompt_version: str = PROMPT_VERSION


@dataclass
class VisualSummaryResult:
    status: str
    summary: str = ""
    provider: str | None = None
    model: str | None = None
    raw: dict[str, Any] | None = None
    error: str | None = None
    cache_key: str | None = None
    warnings: list[str] = field(default_factory=list)
