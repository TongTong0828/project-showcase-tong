"""Trace helpers for paper discovery runs."""

from __future__ import annotations

from typing import Any

from ..observability import new_trace_id


def new_trace(topic: str, sources: list[str], max_candidates: int) -> dict[str, Any]:
    return {
        "trace_id": new_trace_id(),
        "topic": topic,
        "sources": sources,
        "max_candidates": max_candidates,
        "loop": [],
        "source_errors": [],
        "evidence_role": "discovery_only_not_answer_evidence",
    }


def add_stage(trace: dict[str, Any], stage: str, **payload: Any) -> None:
    trace.setdefault("loop", []).append({"stage": stage, **payload})
