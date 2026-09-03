"""Resolve one effective QA query before retrieval starts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from ..utils.logger import get_logger
from .llm import chat

log = get_logger("rag.context_resolver")

Source = Literal[
    "outer_checkpoint",
    "api_resolved",
    "paper_rag_recent_turns",
    "paper_rag_research_memory",
    "none",
]
Policy = Literal["authoritative_outer", "inner_fallback", "single_turn"]
Caller = Literal["host", "rest", "python"]

_REWRITE_PROMPT = """Rewrite the current question for a paper RAG system.

Use recent turns and research memory only to resolve context, topic, and paper
scope. Memory is not evidence and must not be cited.

Recent turns and memory:
{memory}

Current question: {question}

Return one self-contained research question. No explanation.
"""


@dataclass(frozen=True)
class QARequestContext:
    raw_question: str
    outer_resolved_question: str | None
    explicit_paper_ids: tuple[str, ...]
    conversation_id: str | None
    user_id: str
    caller: Caller


@dataclass(frozen=True)
class QueryResolution:
    raw_question: str
    effective_question: str
    source: Source
    policy: Policy
    rewrite_applied: bool
    outer_resolution_used: bool
    explicit_paper_ids: tuple[str, ...]
    memory_paper_scope_hint: tuple[str, ...]
    effective_paper_ids: tuple[str, ...]
    conflicts: tuple[str, ...]
    memory_used_as_evidence: bool = False


def _scope_conflicts(
    explicit_paper_ids: tuple[str, ...],
    scope_hint: tuple[str, ...],
) -> tuple[str, ...]:
    if not explicit_paper_ids or not scope_hint:
        return ()
    explicit = set(explicit_paper_ids)
    hinted = set(scope_hint)
    if hinted.issubset(explicit):
        return ()
    return ("memory_scope_ignored_due_to_explicit_paper_ids",)


def _load_memory_scope_hint(user_id: str, conversation_id: str | None) -> list[str]:
    if not conversation_id:
        return []
    try:
        from . import research_memory

        memory = research_memory.load_for_question(
            conversation_id,
            user_id=user_id or "system",
        )
    except Exception as exc:
        log.warning(f"research memory scope load failed (non-fatal): {exc}")
        return []
    research = memory.get("research_memory") if isinstance(memory, dict) else {}
    if not isinstance(research, dict):
        return []
    values = research.get("read_papers") or []
    return [str(value) for value in values if value]


def _rewrite_with_memory(
    question: str,
    *,
    user_id: str,
    conversation_id: str,
) -> tuple[str, Source]:
    try:
        from . import research_memory

        memory = research_memory.load_for_question(
            conversation_id,
            user_id=user_id or "system",
        )
    except Exception as exc:
        log.warning(f"research memory rewrite load failed (non-fatal): {exc}")
        return question, "none"

    if not memory.get("recent_turns") and not memory.get("has_compressed_memory"):
        return question, "none"

    prompt = (
        _REWRITE_PROMPT
        .replace("{memory}", json.dumps(memory, ensure_ascii=False))
        .replace("{question}", question)
    )
    source: Source = (
        "paper_rag_research_memory"
        if memory.get("has_compressed_memory")
        else "paper_rag_recent_turns"
    )
    try:
        rewritten = chat(
            [{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=160,
        )
        rewritten = rewritten.strip().splitlines()[0] if rewritten.strip() else question
        return rewritten, source
    except Exception as exc:
        log.warning(f"context resolver rewrite failed (non-fatal): {exc}")
        return question, "none"


def resolve_query(ctx: QARequestContext) -> QueryResolution:
    raw = (ctx.raw_question or "").strip()
    outer = (ctx.outer_resolved_question or "").strip()
    scope_hint = tuple(_load_memory_scope_hint(ctx.user_id, ctx.conversation_id))
    conflicts = _scope_conflicts(ctx.explicit_paper_ids, scope_hint)

    if outer:
        return QueryResolution(
            raw_question=raw,
            effective_question=outer,
            source="outer_checkpoint" if ctx.caller == "host" else "api_resolved",
            policy="authoritative_outer",
            rewrite_applied=False,
            outer_resolution_used=True,
            explicit_paper_ids=ctx.explicit_paper_ids,
            memory_paper_scope_hint=scope_hint,
            effective_paper_ids=ctx.explicit_paper_ids,
            conflicts=conflicts,
        )

    if ctx.conversation_id:
        rewritten, source = _rewrite_with_memory(
            raw,
            user_id=ctx.user_id,
            conversation_id=ctx.conversation_id,
        )
        effective = rewritten.strip() or raw
        return QueryResolution(
            raw_question=raw,
            effective_question=effective,
            source=source if effective != raw else "none",
            policy="inner_fallback",
            rewrite_applied=effective != raw,
            outer_resolution_used=False,
            explicit_paper_ids=ctx.explicit_paper_ids,
            memory_paper_scope_hint=scope_hint,
            effective_paper_ids=ctx.explicit_paper_ids,
            conflicts=conflicts,
        )

    return QueryResolution(
        raw_question=raw,
        effective_question=raw,
        source="none",
        policy="single_turn",
        rewrite_applied=False,
        outer_resolution_used=False,
        explicit_paper_ids=ctx.explicit_paper_ids,
        memory_paper_scope_hint=scope_hint,
        effective_paper_ids=ctx.explicit_paper_ids,
        conflicts=conflicts,
    )


def resolution_to_trace(resolution: QueryResolution) -> dict:
    if resolution.policy == "authoritative_outer":
        memory_mode = "scope_only"
    elif resolution.policy == "inner_fallback":
        memory_mode = "rewrite"
    else:
        memory_mode = "off"
    return {
        "raw_question": resolution.raw_question,
        "effective_question": resolution.effective_question,
        "source": resolution.source,
        "policy": resolution.policy,
        "rewrite_applied": resolution.rewrite_applied,
        "outer_resolution_used": resolution.outer_resolution_used,
        "explicit_paper_ids": list(resolution.explicit_paper_ids),
        "memory_paper_scope_hint": list(resolution.memory_paper_scope_hint),
        "effective_paper_ids": list(resolution.effective_paper_ids),
        "conflicts": list(resolution.conflicts),
        "memory_used_as_evidence": resolution.memory_used_as_evidence,
        "context_source": resolution.source,
        "memory_mode": memory_mode,
    }


__all__ = [
    "QARequestContext",
    "QueryResolution",
    "resolution_to_trace",
    "resolve_query",
]
