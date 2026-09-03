"""Paper RAG research memory.

This memory layer is intentionally scoped to paper_rag. It helps long-running
research conversations keep continuity, but it is never treated as answer
evidence. Final QA still has to retrieve paper chunks and cite them.
"""

from __future__ import annotations

import json
from typing import Any

from ..utils.logger import get_logger
from .llm import chat

log = get_logger("rag.research_memory")

_TABLE_READY = False
_RECENT_LIMIT = 3
_COMPRESS_AFTER_TURNS = 6
_COMPRESS_AFTER_ANSWER_CHARS = 6000
_MEMORY_ROLE = "query_context_only_not_evidence"

_EMPTY_RESEARCH_MEMORY: dict[str, list[str]] = {
    "current_topics": [],
    "read_papers": [],
    "confirmed_findings": [],
    "open_questions": [],
    "preferences": [],
}

_SUMMARY_PROMPT = """You compress a paper research conversation into durable research memory.

Important: this memory is query context only, not evidence. It must not be used
as a citation source. Final answers must still retrieve paper chunks.

Return JSON only:
{
  "session_summary": "...",
  "research_memory": {
    "current_topics": ["..."],
    "read_papers": ["arxiv:..."],
    "confirmed_findings": ["..."],
    "open_questions": ["..."],
    "preferences": ["..."]
  }
}

Conversation turns:
{turns}
"""

_REWRITE_PROMPT = """Rewrite the current question for a paper RAG system.

Use the research memory only to resolve context, topic, and paper scope. The
memory is not evidence and must not be cited.

Research memory:
{memory}

Current question: {question}

Return one self-contained research question. No explanation.
"""


def _default_memory(conversation_id: str | None, *, turn_count: int = 0) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "recent_turns": [],
        "session_summary": "",
        "research_memory": _empty_research_memory(),
        "turn_count": turn_count,
        "has_compressed_memory": False,
        "memory_role": _MEMORY_ROLE,
    }


def _empty_research_memory() -> dict[str, list[str]]:
    return {key: list(values) for key, values in _EMPTY_RESEARCH_MEMORY.items()}


def _ensure_tables() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    from . import conversation_turn_store as turns

    turns._ensure_tables()
    _TABLE_READY = True


def _json_loads(value: str, default):
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _extract_paper_ids(trace: dict[str, Any] | None) -> list[str]:
    if not isinstance(trace, dict):
        return []
    candidates = trace.get("chunks") or trace.get("final_chunks") or []
    paper_ids = [
        str(ch.get("paper_id"))
        for ch in candidates
        if isinstance(ch, dict) and ch.get("paper_id")
    ]
    return _dedupe(paper_ids)


def append(
    conversation_id: str | None,
    question: str,
    answer: str,
    citations: list[str],
    *,
    trace: dict[str, Any] | None = None,
    user_id: str = "system",
    effective_question: str | None = None,
    resolution_source: str = "paper_rag",
) -> dict[str, Any]:
    """Append one turn and compress when the lightweight trigger fires."""
    if not conversation_id:
        return {"enabled": False, **_default_memory(conversation_id)}

    from . import conversation_turn_store as turns

    _ensure_tables()
    paper_ids = _extract_paper_ids(trace)
    turns.append_turn(
        user_id=user_id,
        conversation_id=conversation_id,
        raw_question=question,
        effective_question=effective_question or question,
        answer=answer[:4000],
        citations=citations,
        paper_ids=paper_ids,
        trace=trace or {},
        resolution_source=resolution_source,
    )

    stats = _stats(conversation_id, user_id=user_id)
    compressed = False
    if (
        stats["turn_count"] > _COMPRESS_AFTER_TURNS
        or stats["answer_chars"] > _COMPRESS_AFTER_ANSWER_CHARS
    ):
        summarize(conversation_id, user_id=user_id)
        compressed = True

    return {
        **load_for_question(conversation_id, user_id=user_id),
        "compressed": compressed,
    }


def _stats(conversation_id: str, *, user_id: str = "system") -> dict[str, int]:
    from sqlalchemy import text

    from ..store.sqlite_store import get_engine
    from . import conversation_turn_store as turns

    _ensure_tables()
    turns.recent_turns(user_id=user_id, conversation_id=conversation_id, limit=1)
    with get_engine().begin() as conn:
        row = conn.execute(
            text(
                "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(answer)), 0) AS chars "
                "FROM conversation_turns WHERE user_id = :u AND conversation_id = :c"
            ),
            {"u": user_id or "system", "c": conversation_id},
        ).fetchone()
    return {"turn_count": int(row[0] or 0), "answer_chars": int(row[1] or 0)}


def _recent_rows(
    conversation_id: str,
    limit: int = _RECENT_LIMIT,
    *,
    user_id: str = "system",
) -> list[dict[str, Any]]:
    from . import conversation_turn_store as turns

    _ensure_tables()
    out = []
    for turn in turns.recent_turns(
        user_id=user_id,
        conversation_id=conversation_id,
        limit=limit,
    ):
        out.append(
            {
                "question": turn.raw_question,
                "answer_preview": (turn.answer or "")[:500],
                "citations": turn.citations,
                "paper_ids": turn.paper_ids,
                "created_at": turn.created_at,
            }
        )
    return out


def _summary_row(conversation_id: str, *, user_id: str = "system") -> dict[str, Any] | None:
    from . import conversation_turn_store as turns

    _ensure_tables()
    row = turns.load_summary(user_id=user_id, conversation_id=conversation_id)
    if not row:
        return None
    return {
        "session_summary": row["session_summary"],
        "research_memory": _normalize_research_memory(row["research_memory"]),
        "n_turns": int(row["n_turns"] or 0),
        "updated_at": row["updated_at"],
    }


def load_for_question(
    conversation_id: str | None,
    *,
    user_id: str = "system",
) -> dict[str, Any]:
    """Load compressed memory plus recent turns for query rewriting."""
    if not conversation_id:
        return _default_memory(conversation_id)

    _ensure_tables()
    stats = _stats(conversation_id, user_id=user_id)
    summary = _summary_row(conversation_id, user_id=user_id)
    memory = _default_memory(conversation_id, turn_count=stats["turn_count"])
    memory["recent_turns"] = _recent_rows(conversation_id, user_id=user_id)
    if summary:
        memory["session_summary"] = summary["session_summary"]
        memory["research_memory"] = summary["research_memory"]
        memory["has_compressed_memory"] = bool(summary["session_summary"])
    return memory


def summarize(conversation_id: str, *, user_id: str = "system") -> dict[str, Any]:
    """Compress all turns for a conversation into a small research memory."""
    from sqlalchemy import text

    from ..store.sqlite_store import get_engine
    from . import conversation_turn_store as turns

    _ensure_tables()
    turns.recent_turns(user_id=user_id, conversation_id=conversation_id, limit=1)
    with get_engine().begin() as conn:
        rows = list(
            conn.execute(
                text(
                    "SELECT raw_question, answer, citations_json, paper_ids_json "
                    "FROM conversation_turns "
                    "WHERE user_id = :u AND conversation_id = :c "
                    "ORDER BY id ASC"
                ),
                {"u": user_id or "system", "c": conversation_id},
            )
        )

    payload = _summarize_rows(rows)
    turns.append_summary(
        user_id=user_id,
        conversation_id=conversation_id,
        session_summary=payload["session_summary"],
        research_memory=payload["research_memory"],
        n_turns=len(rows),
    )
    return load_for_question(conversation_id, user_id=user_id)


def _summarize_rows(rows) -> dict[str, Any]:
    turns = []
    for i, row in enumerate(rows, start=1):
        citations = _json_loads(row[2], [])
        paper_ids = _json_loads(row[3], [])
        turns.append(
            f"Turn {i}\nQ: {row[0]}\nA: {(row[1] or '')[:700]}\n"
            f"Citations: {citations}\nPapers: {paper_ids}"
        )
    prompt = _SUMMARY_PROMPT.replace("{turns}", "\n\n".join(turns))
    try:
        raw = chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=700)
        parsed = json.loads(raw)
        return {
            "session_summary": str(parsed.get("session_summary") or "").strip(),
            "research_memory": _normalize_research_memory(parsed.get("research_memory") or {}),
        }
    except Exception as exc:
        log.warning(f"research memory summarize failed; using fallback: {exc}")
        return _fallback_summary(rows)


def _fallback_summary(rows) -> dict[str, Any]:
    if not rows:
        return {"session_summary": "", "research_memory": _empty_research_memory()}

    last_q = str(rows[-1][0])
    last_a = str(rows[-1][1] or "")[:240]
    paper_ids: list[str] = []
    findings: list[str] = []
    for row in rows:
        paper_ids.extend(_json_loads(row[3], []))
        answer = str(row[1] or "").strip()
        if answer:
            findings.append(answer[:180])
    return {
        "session_summary": f"Recent research thread. Latest question: {last_q} Latest answer: {last_a}",
        "research_memory": {
            "current_topics": [],
            "read_papers": _dedupe(paper_ids),
            "confirmed_findings": _dedupe(findings[-3:]),
            "open_questions": [last_q],
            "preferences": [],
        },
    }


def _normalize_research_memory(value: dict[str, Any]) -> dict[str, list[str]]:
    out = _empty_research_memory()
    for key in out:
        raw = value.get(key, []) if isinstance(value, dict) else []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            raw = []
        out[key] = _dedupe([str(item) for item in raw if item])
    return out


def rewrite_with_memory(
    question: str,
    conversation_id: str | None,
    *,
    user_id: str = "system",
) -> tuple[str, dict[str, Any]]:
    """Rewrite a question using compressed memory when available."""
    memory = load_for_question(conversation_id, user_id=user_id)
    if not conversation_id or not memory.get("has_compressed_memory"):
        return question, memory

    prompt = (
        _REWRITE_PROMPT
        .replace("{memory}", json.dumps(memory, ensure_ascii=False))
        .replace("{question}", question)
    )
    try:
        rewritten = chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=160)
        rewritten = rewritten.strip().splitlines()[0] if rewritten.strip() else question
        if rewritten != question:
            memory = {**memory, "rewrite_applied": True, "rewritten_question": rewritten}
        return rewritten, memory
    except Exception as exc:
        log.warning(f"research memory rewrite failed: {exc}; using original question")
        return question, {**memory, "rewrite_error": type(exc).__name__}


__all__ = [
    "append",
    "load_for_question",
    "rewrite_with_memory",
    "summarize",
]
