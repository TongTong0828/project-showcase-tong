"""Streaming variant of qa_agentic.

Yields events as the pipeline progresses, so callers (e.g. DeerFlow lead
agent or a chat UI) can render incrementally instead of waiting for the
full ~2-min answer.

Event types:
    {"event": "intent",     "data": {"intent": "factual", "top_k": 5, ...}}
    {"event": "rewrite",    "data": {"queries": [...], "keywords": "..."}}
    {"event": "retrieved",  "data": {"iter": 0, "n_chunks": 7}}
    {"event": "reflect",    "data": {"sufficiency": "sufficient", ...}}
    {"event": "abstain",    "data": {"decision": "confident|weak|no_evidence|...", ...}}
    {"event": "answer_chunk","data": {"text": "..."}}
    {"event": "done",       "data": {"citations": [...], "suspicious": {...}, "abstain": {...}}}
    {"event": "error",      "data": {"message": "..."}}

Same hard caps as qa_agentic (max_inner_iters / max_inner_tokens).
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from .. import config as cfg
from ..retrieve.format import format_evidence
from ..retrieve.pipeline import retrieve_round_with_rewrite
from ..utils.logger import get_logger
from . import abstain as abstain_mod
from .citation_check import (
    detect_suspicious_citations,
    strip_suspicious_citation_forms,
    validate_citations,
)
from .evidence_select import select_evidence
from .intent_classifier import classify
from .query_rewrite import rewrite  # re-exported so tests can monkey-patch qa_stream.rewrite
from .reflect import reflect

log = get_logger("rag.qa_stream")

_SYSTEM = (
    "You are a careful academic research assistant. Answer ONLY using the "
    "evidence chunks provided. After each factual statement, cite the chunk "
    "with [chunk:<chunk_id>]. NEVER use [1], [2], or (Author 2020) style "
    "citations. Keep the answer concise (≤200 words). If insufficient "
    "evidence, say so explicitly."
)


def _retrieve_round(query: str, paper_ids, top_k: int) -> tuple[list[dict], dict]:
    # Pass our module's `rewrite` reference so that tests monkey-patching
    # qa_stream.rewrite are still honoured.
    return retrieve_round_with_rewrite(query, paper_ids, top_k, rewrite_fn=rewrite)


def _persist_stream_research_memory(
    *,
    conversation_id: str | None,
    resolution,
    done_data: dict[str, Any],
    final_chunks: list[dict],
    query_resolution: dict,
    user_id: str,
) -> None:
    if not conversation_id:
        return
    try:
        from . import research_memory

        research_memory.append(
            conversation_id,
            resolution.raw_question,
            done_data.get("answer", ""),
            done_data.get("citations", []),
            trace={
                "chunks": final_chunks,
                "query_resolution": query_resolution,
                "abstain": done_data.get("abstain") or {},
            },
            user_id=user_id or "system",
            effective_question=resolution.effective_question,
            resolution_source=resolution.source,
        )
    except Exception as exc:
        log.warning(f"stream research memory append failed (non-fatal): {exc}")


def stream_answer(
    question: str,
    *,
    paper_ids: list[str] | None = None,
    conversation_id: str | None = None,
    user_id: str = "system",
    resolved_question: str | None = None,
) -> Generator[dict, None, None]:
    """Yield events as the agentic pipeline progresses."""
    from .context_resolver import QARequestContext, resolution_to_trace, resolve_query

    resolution = resolve_query(
        QARequestContext(
            raw_question=question,
            outer_resolved_question=resolved_question,
            explicit_paper_ids=tuple(paper_ids or ()),
            conversation_id=conversation_id,
            user_id=user_id or "system",
            caller="python",
        )
    )
    query_resolution = resolution_to_trace(resolution)
    question = resolution.effective_question
    paper_ids = list(resolution.effective_paper_ids) or None

    c = cfg.load().rag
    intent_cfg = classify(question)
    yield {"event": "intent", "data": intent_cfg}

    max_iter = min(intent_cfg["max_iter"], c.max_inner_iters)
    top_k = intent_cfg["top_k"]
    all_chunks: dict[str, dict] = {}
    current_query = question

    for it in range(max_iter):
        try:
            chunks, rw = _retrieve_round(current_query, paper_ids, top_k)
        except Exception as e:
            yield {"event": "error", "data": {"message": f"retrieve failed: {e}"}}
            return
        if it == 0:
            yield {"event": "rewrite", "data": {
                "queries": rw.get("dense_queries", []),
                "keywords": rw.get("bm25_query", ""),
            }}
        for ch in chunks:
            cid = ch.get("chunk_id")
            if cid and cid not in all_chunks:
                all_chunks[cid] = ch
        yield {"event": "retrieved", "data": {"iter": it, "n_chunks": len(chunks)}}

        if not chunks:
            break
        if c.enable_reflect and it < max_iter - 1:
            r = reflect(question, format_evidence(chunks))
            yield {"event": "reflect", "data": r}
            if r["sufficiency"] == "sufficient":
                break
            if r["follow_up"]:
                current_query = r["follow_up"]
                continue
            break
        else:
            break

    final_chunks = list(all_chunks.values())[: top_k * 2]
    if not final_chunks:
        done_data = {
            "answer": "(no evidence found)",
            "citations": [],
            "suspicious": {"count": 0},
            "degraded": "no_chunks",
            "abstain": {"decision": abstain_mod.DECISION_NO_CHUNKS},
            "query_resolution": query_resolution,
        }
        _persist_stream_research_memory(
            conversation_id=conversation_id,
            resolution=resolution,
            done_data=done_data,
            final_chunks=final_chunks,
            query_resolution=query_resolution,
            user_id=user_id,
        )
        yield {"event": "done", "data": done_data}
        return

    # === ADR-0014 abstain decision ===
    abstain_cfg = c.abstain
    abstain_result = abstain_mod.decide(
        final_chunks,
        enabled=abstain_cfg.enabled,
        threshold_low=abstain_cfg.threshold_low,
        threshold_high=abstain_cfg.threshold_high,
        min_chunks=abstain_cfg.min_chunks,
    )
    yield {"event": "abstain", "data": abstain_result}

    if abstain_result["decision"] == abstain_mod.DECISION_NO_EVIDENCE:
        # Skip the LLM stream entirely.
        yield {"event": "answer_chunk", "data": {"text": abstain_cfg.no_evidence_message}}
        done_data = {
            "answer": abstain_cfg.no_evidence_message,
            "citations": [],
            "suspicious": {"count": 0},
            "abstain": abstain_result,
            "n_chunks": len(final_chunks),
            "query_resolution": query_resolution,
        }
        _persist_stream_research_memory(
            conversation_id=conversation_id,
            resolution=resolution,
            done_data=done_data,
            final_chunks=final_chunks,
            query_resolution=query_resolution,
            user_id=user_id,
        )
        yield {"event": "done", "data": done_data}
        return

    evidence_chunks, evidence_selection = select_evidence(
        question,
        final_chunks,
        intent=intent_cfg.get("intent"),
    )

    # Stream the answer token by token.
    allowed_citations = " ".join(
        f"[chunk:{ch['chunk_id']}]" for ch in evidence_chunks if ch.get("chunk_id")
    )
    user = (
        f"Question: {question}\n\nEvidence:\n{format_evidence(evidence_chunks)}\n\n"
        f"Allowed citation tokens: {allowed_citations}\n\n"
        "Use at most 2 citations. Choose the chunks that most directly support "
        "the answer; do not cite background chunks just because they are available.\n\n"
        "Answer (copy citation tokens EXACTLY from the allowed list; never invent "
        "[chunk:1], [chunk:2], [1], or (Author 2020) citations; ≤200 words):"
    )
    if abstain_result["decision"] == abstain_mod.DECISION_WEAK:
        user += abstain_mod.WEAK_EVIDENCE_HINT
    full = ""
    try:
        for tok in _stream_chat(_SYSTEM, user):
            full += tok
            yield {"event": "answer_chunk", "data": {"text": tok}}
    except Exception as e:
        yield {"event": "error", "data": {"message": f"chat stream failed: {e}"}}
        return

    cleaned, valid = validate_citations(full, evidence_chunks)
    suspicious = detect_suspicious_citations(cleaned)
    if suspicious["count"]:
        cleaned = strip_suspicious_citation_forms(cleaned)
    paper_ids_used = sorted({c.get("paper_id") for c in final_chunks if c.get("paper_id")})
    done_data = {
        "answer": cleaned,
        "citations": valid,
        "suspicious": suspicious,
        "abstain": abstain_result,
        "n_chunks": len(final_chunks),
        "evidence_chunks": evidence_chunks,
        "evidence_selection": evidence_selection,
        "paper_ids": paper_ids_used,
        "query_resolution": query_resolution,
    }
    _persist_stream_research_memory(
        conversation_id=conversation_id,
        resolution=resolution,
        done_data=done_data,
        final_chunks=final_chunks,
        query_resolution=query_resolution,
        user_id=user_id,
    )
    yield {"event": "done", "data": done_data}


def _stream_chat(system: str, user: str):
    """Yield string tokens from the OpenAI-compatible streaming endpoint."""
    c = cfg.load().llm
    chosen = c.chat_model
    if not chosen:
        raise RuntimeError("CHAT_MODEL not set")
    from .llm import get_client

    resp = get_client().chat.completions.create(
        model=chosen,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=c.temperatures.stream,
        max_tokens=600,
        stream=True,
    )
    for chunk in resp:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and getattr(delta, "content", None):
            yield delta.content
