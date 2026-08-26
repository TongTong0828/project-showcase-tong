"""Agentic paper_qa: intent -> rewrite -> hybrid retrieve -> rerank -> reflect -> iterate.

Closed-loop: the lead agent only sees ONE tool call; all internal hops happen here.
Hard caps: max_inner_iters and max_inner_tokens from config.

Output:
    {
      "answer": str,
      "citations": [chunk_id, ...],
      "chunks": [...],          # final chunks used for the answer
      "trace": {                # for debugging/inspection
        "intent": ...,
        "iters": [{"query":..., "n_retrieved":..., "reflect":...}, ...],
        "stopped_by": "answered" | "max_iters" | "no_evidence",
      }
    }
"""

from __future__ import annotations

from time import perf_counter

from .. import config as cfg
from ..retrieve.format import format_evidence
from ..retrieve.pipeline import retrieve_round as _retrieve_round
from ..utils.logger import get_logger
from . import abstain as abstain_mod
from .citation_check import (
    detect_suspicious_citations,
    strip_suspicious_citation_forms,
    validate_citations,
)
from .context_resolver import (
    QARequestContext,
    QueryResolution,
    resolution_to_trace,
    resolve_query,
)
from .evidence_select import select_evidence
from .intent_classifier import classify
from .llm import chat
from .reflect import reflect

log = get_logger("rag.qa_agentic")

_SYSTEM = (
    "You are a careful academic research assistant. Answer ONLY using the "
    "evidence chunks provided. After each factual statement, cite the chunk "
    "with [chunk:<chunk_id>]. NEVER use [1], [2], or (Author 2020) style "
    "citations — they will be considered hallucinated. Keep the answer "
    "concise: at most 200 words, dense and informative, no padding. If the "
    "evidence is insufficient, say so explicitly. Do NOT fabricate paper "
    "titles, numbers, authors, or years."
)

_EMPTY_SUSPICIOUS: dict = {"numeric": [], "author_year": [], "count": 0}


# ---------------------------------------------------------------------------
# Stage helpers — each stage is independently unit-testable.
# ---------------------------------------------------------------------------


def _maybe_rewrite_with_history(question: str, conversation_id: str | None) -> str:
    """If the request belongs to a multi-turn conversation, fold the history
    into a self-contained question. Failures are non-fatal."""
    if not conversation_id:
        return question
    try:
        from . import history

        rewritten = history.rewrite_with_history(question, conversation_id)
        if rewritten != question:
            log.info(f"history rewrite: {question!r} -> {rewritten!r}")
        return rewritten
    except Exception as e:
        log.warning(f"history rewrite failed (non-fatal): {e}")
        return question


def _resolve_wiki_context_safe(question: str, paper_ids: list[str] | None) -> dict:
    """Resolve wiki background for QA. Failures are non-fatal."""
    try:
        from ..wiki.context import resolve_wiki_context

        return resolve_wiki_context(question, paper_ids=paper_ids)
    except Exception as e:
        log.warning(f"wiki context resolve failed (non-fatal): {e}")
        return {"role": "background_not_evidence", "fingerprint": "", "entries": []}


def _cache_question(
    resolution: QueryResolution,
    wiki_context: dict | None,
    *,
    user_id: str,
) -> str:
    trace = resolution_to_trace(resolution)
    question = resolution.effective_question
    parts = [
        question,
        "",
        "pipeline:qra-v1",
        f"user:{user_id or 'system'}",
        f"memory_mode:{trace['memory_mode']}",
        f"context_source:{trace['context_source']}",
    ]
    fingerprint = (wiki_context or {}).get("fingerprint") or ""
    if fingerprint:
        parts.append(f"wiki_context_fingerprint:{fingerprint}")
    return "\n".join(parts)


def _record_wiki_consumption_safe(
    *,
    question: str,
    paper_ids: list[str] | None,
    wiki_context: dict,
    trace_id: str,
) -> None:
    if not (wiki_context or {}).get("entries"):
        return
    try:
        from ..wiki.usage import record_consumption

        record_consumption(
            question=question,
            paper_ids=paper_ids,
            wiki_context=wiki_context,
            trace_id=trace_id,
        )
    except Exception as e:
        log.warning(f"wiki consumption record failed (non-fatal): {e}")


def _check_cache(
    question: str,
    paper_ids: list[str] | None,
    trace_id: str,
    *,
    user_id: str = "system",
) -> dict | None:
    """qa_cache short-circuit. Returns the cached response (already shaped
    for the public ``answer`` contract) or None if no hit."""
    try:
        from ..observability import counter
        from . import qa_cache

        cached = qa_cache.get(question, paper_ids, user_id=user_id)
    except Exception as e:
        log.warning(f"qa_cache get failed (non-fatal): {e}")
        return None
    if cached is None:
        return None
    counter("paper_rag_qa_total", {"stop": "cache_hit"}).inc()
    return {
        "answer": cached.get("answer", ""),
        "citations": cached.get("citations", []),
        "chunks": cached.get("chunks") or [],
        "suspicious_citations": cached.get("suspicious_citations", _EMPTY_SUSPICIOUS),
        "trace": {
            **(cached.get("trace") or {}),
            "from_cache": True,
            "trace_id": trace_id,
            "cached_chunk_ids": cached.get("chunk_ids", []),
        },
    }


def _retrieve_loop(
    question: str,
    paper_ids: list[str] | None,
    top_k: int,
    max_iter: int,
    enable_reflect: bool,
    wiki_context: dict | None = None,
) -> tuple[dict[str, dict], list[dict], str]:
    """Run up to ``max_iter`` rounds of retrieve+reflect.

    Returns (all_chunks, trace, stopped_by).
    """
    all_chunks: dict[str, dict] = {}
    trace: list[dict] = []
    current_query = question
    stopped = "max_iters"

    for it in range(max_iter):
        try:
            chunks = _retrieve_round(
                current_query, paper_ids, top_k, wiki_context=wiki_context
            )
        except TypeError as e:
            if "wiki_context" not in str(e):
                raise
            chunks = _retrieve_round(current_query, paper_ids, top_k)
        for ch in chunks:
            cid = ch.get("chunk_id")
            if cid and cid not in all_chunks:
                all_chunks[cid] = ch

        if not chunks:
            trace.append({"query": current_query, "n_retrieved": 0, "reflect": None})
            stopped = "no_evidence"
            break

        if enable_reflect and it < max_iter - 1:
            r = reflect(question, format_evidence(chunks))
            trace.append({"query": current_query, "n_retrieved": len(chunks), "reflect": r})
            if r["sufficiency"] == "sufficient":
                stopped = "answered"
                break
            if r["follow_up"]:
                current_query = r["follow_up"]
                continue
            stopped = "answered"
            break

        trace.append({"query": current_query, "n_retrieved": len(chunks), "reflect": None})
        stopped = "answered"
        break

    return all_chunks, trace, stopped


def _no_chunks_response(
    intent_cfg: dict,
    trace: list[dict],
    stopped: str,
    trace_id: str,
    wiki_context: dict | None = None,
) -> dict:
    """Final response when retrieve produced zero usable chunks."""
    from ..observability import counter

    counter("paper_rag_qa_total", {"intent": intent_cfg["intent"], "stop": "no_chunks"}).inc()
    counter("paper_rag_qa_degraded_total", {"reason": "no_chunks"}).inc()
    counter("paper_rag_qa_abstain_total", {"decision": abstain_mod.DECISION_NO_CHUNKS}).inc()
    return {
        "answer": "(no evidence found in the indexed papers)",
        "citations": [],
        "chunks": [],
        "suspicious_citations": _EMPTY_SUSPICIOUS,
        "trace": {
            "intent": intent_cfg,
            "iters": trace,
            "stopped_by": stopped,
            "degraded": "no_chunks",
            "abstain": {
                "decision": abstain_mod.DECISION_NO_CHUNKS,
                "evidence_score": 0.0,
                "n_chunks": 0,
            },
            "wiki_context": wiki_context or {"role": "background_not_evidence", "fingerprint": "", "entries": []},
            "trace_id": trace_id,
        },
    }


def _decide_abstain(final_chunks: list[dict], abstain_cfg) -> dict:
    """Run abstain.decide and emit the matching counters/log line."""
    from ..observability import counter

    result = abstain_mod.decide(
        final_chunks,
        enabled=abstain_cfg.enabled,
        threshold_low=abstain_cfg.threshold_low,
        threshold_high=abstain_cfg.threshold_high,
        min_chunks=abstain_cfg.min_chunks,
    )
    counter("paper_rag_qa_abstain_total", {"decision": result["decision"]}).inc()
    if result.get("signal_quality") == "low_degraded":
        counter("paper_rag_qa_degraded_total", {"reason": "abstain_low_quality_signal"}).inc()
    log.info(
        f"abstain decision: {result['decision']} "
        f"score={result['evidence_score']:.3f} "
        f"top={result['top_chunk_score']:.3f} "
        f"field={result['score_field']} "
        f"quality={result.get('signal_quality')} "
        f"n={result['n_chunks']}"
    )
    return result


def _no_evidence_response(
    intent_cfg: dict,
    trace: list[dict],
    abstain_result: dict,
    abstain_cfg,
    final_chunks: list[dict],
    trace_id: str,
    wiki_context: dict | None = None,
) -> dict:
    """Skip the LLM entirely when abstain says no_evidence."""
    from ..observability import counter

    counter(
        "paper_rag_qa_total",
        {"intent": intent_cfg["intent"], "stop": "no_evidence_abstain"},
    ).inc()
    return {
        "answer": abstain_cfg.no_evidence_message,
        "citations": [],
        "chunks": final_chunks,  # still return chunks for inspection / debug
        "suspicious_citations": _EMPTY_SUSPICIOUS,
        "trace": {
            "intent": intent_cfg,
            "iters": trace,
            "stopped_by": "no_evidence_abstain",
            "abstain": abstain_result,
            "wiki_context": wiki_context or {"role": "background_not_evidence", "fingerprint": "", "entries": []},
            "trace_id": trace_id,
        },
    }


def _build_user_prompt(
    question: str,
    final_chunks: list[dict],
    abstain_result: dict,
    wiki_context: dict | None = None,
) -> str:
    evidence = format_evidence(final_chunks)
    wiki_block = ""
    try:
        from ..wiki.context import format_wiki_background

        wiki_block = format_wiki_background(wiki_context or {})
    except Exception as e:
        log.warning(f"wiki background formatting failed (non-fatal): {e}")
    allowed_citations = " ".join(
        f"[chunk:{ch['chunk_id']}]" for ch in final_chunks if ch.get("chunk_id")
    )
    wiki_section = f"\n\n{wiki_block}\n" if wiki_block else ""
    user = (
        f"Question: {question}{wiki_section}\nEvidence:\n{evidence}\n\n"
        f"Allowed citation tokens: {allowed_citations}\n\n"
        "Use at most 2 citations. Choose the chunks that most directly support "
        "the answer; do not cite background chunks just because they are available.\n\n"
        "Answer (copy citation tokens EXACTLY from the allowed list; never invent "
        "[chunk:1], [chunk:2], [1], or (Author 2020) citations):"
    )
    if abstain_result["decision"] == abstain_mod.DECISION_WEAK:
        # Inject explicit insufficiency hint — the LLM may still answer, but
        # is told to flag uncertainty rather than hallucinate citations.
        user += abstain_mod.WEAK_EVIDENCE_HINT
    return user


def _chat_failed_response(
    intent_cfg: dict,
    trace: list[dict],
    stopped: str,
    final_chunks: list[dict],
    evidence_chunks: list[dict],
    evidence_selection: dict,
    trace_id: str,
    err: Exception,
    wiki_context: dict | None = None,
) -> dict:
    from ..observability import counter

    counter(
        "paper_rag_qa_total",
        {"intent": intent_cfg["intent"], "stop": "chat_error"},
    ).inc()
    counter("paper_rag_qa_degraded_total", {"reason": "chat_error"}).inc()
    return {
        "answer": "(LLM unavailable; see chunks for evidence)",
        "citations": [],
        "chunks": final_chunks,
        "evidence_chunks": evidence_chunks,
        "suspicious_citations": _EMPTY_SUSPICIOUS,
        "trace": {
            "intent": intent_cfg,
            "iters": trace,
            "stopped_by": stopped,
            "degraded": f"chat_error:{type(err).__name__}",
            "evidence_selection": evidence_selection,
            "wiki_context": wiki_context or {"role": "background_not_evidence", "fingerprint": "", "entries": []},
            "trace_id": trace_id,
        },
    }


def _store_in_cache(
    question: str,
    paper_ids: list[str] | None,
    out: dict,
    *,
    user_id: str = "system",
) -> None:
    try:
        from . import qa_cache

        qa_cache.put(question, paper_ids, out, user_id=user_id)
    except Exception as e:
        log.warning(f"qa_cache put failed (non-fatal): {e}")


def _first_wiki_concept(wiki_context: dict | None) -> str | None:
    entries = (wiki_context or {}).get("entries") or []
    if not entries:
        return None
    name = entries[0].get("name")
    return str(name) if name else None


def _first_paper_id(paper_ids: list[str] | None, chunks: list[dict] | None) -> str | None:
    if paper_ids:
        return paper_ids[0]
    for chunk in chunks or []:
        paper_id = chunk.get("paper_id")
        if paper_id:
            return str(paper_id)
    return None


def _enqueue_wiki_review_event(
    event_type: str,
    *,
    question: str,
    paper_ids: list[str] | None = None,
    chunks: list[dict] | None = None,
    wiki_context: dict | None = None,
    reason: str = "",
    trace_id: str | None = None,
    payload: dict | None = None,
    concept: str | None = None,
    paper_id: str | None = None,
) -> None:
    try:
        from ..wiki import review_queue

        review_queue.enqueue(
            event_type,
            concept=concept or _first_wiki_concept(wiki_context),
            paper_id=paper_id or _first_paper_id(paper_ids, chunks),
            question=question,
            reason=reason,
            payload={
                "trace_id": trace_id,
                "wiki_context_fingerprint": (wiki_context or {}).get("fingerprint", ""),
                **(payload or {}),
            },
        )
    except Exception as e:
        log.warning(f"wiki review enqueue failed (non-fatal): {e}")


def _persist_history(
    conversation_id: str | None, question: str, out: dict
) -> None:
    if not conversation_id:
        return
    try:
        from . import history

        history.append(
            conversation_id,
            question,
            out.get("answer", ""),
            out.get("citations", []),
        )
    except Exception as e:
        log.warning(f"history.append failed (non-fatal): {e}")


def _maybe_rewrite_with_research_memory(
    question: str,
    conversation_id: str | None,
) -> tuple[str, dict]:
    """Use compressed research memory as query context, never as evidence."""
    if not conversation_id:
        return question, {
            "conversation_id": conversation_id,
            "memory_role": "query_context_only_not_evidence",
            "has_compressed_memory": False,
        }
    try:
        from . import research_memory

        rewritten, memory = research_memory.rewrite_with_memory(question, conversation_id)
        if rewritten != question:
            log.info(f"research memory rewrite: {question!r} -> {rewritten!r}")
        return rewritten, memory
    except Exception as e:
        log.warning(f"research memory rewrite failed (non-fatal): {e}")
        return question, {
            "conversation_id": conversation_id,
            "memory_role": "query_context_only_not_evidence",
            "has_compressed_memory": False,
            "error": type(e).__name__,
        }


def _attach_loop_trace(out: dict, *, latency_ms: int) -> None:
    """Normalize existing debug trace into a product-readable loop trace."""
    trace = out.setdefault("trace", {})
    intent_cfg = trace.get("intent") or {}
    intent_name = intent_cfg.get("intent") if isinstance(intent_cfg, dict) else str(intent_cfg)
    iterations = trace.get("iters") or []
    chunks = out.get("chunks") or []
    evidence_chunks = out.get("evidence_chunks") or chunks
    trace["loop"] = {
        "intent": intent_name or "unknown",
        "intent_config": intent_cfg,
        "iterations": iterations,
        "stopped_by": trace.get("stopped_by", "unknown"),
        "abstain": trace.get("abstain") or {},
        "citations": out.get("citations", []),
        "n_chunks": len(chunks),
        "n_evidence_chunks": len(evidence_chunks),
        "latency_ms": latency_ms,
        "cost": {
            "llm_calls": None,
            "tokens": None,
            "note": "placeholder; provider usage accounting is not wired in v1",
        },
    }


def _persist_research_memory(
    conversation_id: str | None,
    question: str,
    out: dict,
    *,
    user_id: str = "system",
    effective_question: str | None = None,
    resolution_source: str = "paper_rag",
) -> dict:
    if not conversation_id:
        return {
            "conversation_id": conversation_id,
            "memory_role": "query_context_only_not_evidence",
            "has_compressed_memory": False,
        }
    try:
        from . import research_memory

        trace_for_memory = {
            **(out.get("trace") or {}),
            "chunks": out.get("chunks") or [],
        }
        return research_memory.append(
            conversation_id,
            question,
            out.get("answer", ""),
            out.get("citations", []),
            trace=trace_for_memory,
            user_id=user_id,
            effective_question=effective_question,
            resolution_source=resolution_source,
        )
    except Exception as e:
        log.warning(f"research_memory.append failed (non-fatal): {e}")
        return {
            "conversation_id": conversation_id,
            "memory_role": "query_context_only_not_evidence",
            "has_compressed_memory": False,
            "error": type(e).__name__,
        }


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def answer(
    question: str,
    *,
    paper_ids: list[str] | None = None,
    conversation_id: str | None = None,
    user_id: str = "system",
    resolved_question: str | None = None,
) -> dict:
    from ..observability import histogram, new_trace_id

    trace_id = new_trace_id()
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
    effective_paper_ids = list(resolution.effective_paper_ids) or None
    timer = histogram("paper_rag_qa_latency_seconds")
    started = perf_counter()
    with timer.time():
        out = _answer_impl(
            resolution,
            paper_ids=effective_paper_ids,
            trace_id=trace_id,
            conversation_id=conversation_id,
            user_id=user_id or "system",
        )
    latency_ms = int((perf_counter() - started) * 1000)
    _attach_loop_trace(out, latency_ms=latency_ms)
    resolution_trace = resolution_to_trace(resolution)
    out.setdefault("trace", {})["query_resolution"] = resolution_trace
    out["query_resolution"] = resolution_trace
    memory_after = _persist_research_memory(
        conversation_id,
        resolution.raw_question,
        out,
        user_id=user_id or "system",
        effective_question=resolution.effective_question,
        resolution_source=resolution.source,
    )
    out.setdefault("trace", {})["memory"] = memory_after
    return out


def _answer_impl(
    question: str | QueryResolution,
    *,
    paper_ids: list[str] | None,
    trace_id: str,
    conversation_id: str | None = None,
    user_id: str = "system",
) -> dict:
    from ..observability import counter

    if isinstance(question, QueryResolution):
        query_resolution = question
    else:
        query_resolution = QueryResolution(
            raw_question=question,
            effective_question=question,
            source="none",
            policy="single_turn",
            rewrite_applied=False,
            outer_resolution_used=False,
            explicit_paper_ids=tuple(paper_ids or ()),
            memory_paper_scope_hint=(),
            effective_paper_ids=tuple(paper_ids or ()),
            conflicts=(),
        )
    question = query_resolution.effective_question
    effective_paper_ids = list(query_resolution.effective_paper_ids) or None

    # Stage 1 — resolve wiki background. Wiki is query/prompt context only,
    # never final evidence.
    wiki_context = _resolve_wiki_context_safe(question, effective_paper_ids)
    _record_wiki_consumption_safe(
        question=question,
        paper_ids=effective_paper_ids,
        wiki_context=wiki_context,
        trace_id=trace_id,
    )

    # Stage 2 — qa_cache short-circuit. The effective key includes query
    # resolution policy, user scope, and wiki entry versions so context-specific
    # questions like "it?" cannot reuse another thread's answer.
    question_for_cache = _cache_question(query_resolution, wiki_context, user_id=user_id)
    if (user_id or "system") == "system":
        cached = _check_cache(question_for_cache, effective_paper_ids, trace_id)
    else:
        cached = _check_cache(
            question_for_cache,
            effective_paper_ids,
            trace_id,
            user_id=user_id,
        )
    if cached is not None:
        return cached

    # Stage 3 — pick intent + retrieve loop.
    c = cfg.load().rag
    intent_cfg = classify(question)
    max_iter = min(intent_cfg["max_iter"], c.max_inner_iters)
    top_k = intent_cfg["top_k"]
    all_chunks, trace, stopped = _retrieve_loop(
        question,
        effective_paper_ids,
        top_k,
        max_iter,
        enable_reflect=c.enable_reflect,
        wiki_context=wiki_context,
    )

    # Stage 4 — short-circuit if retrieve produced nothing.
    final_chunks = list(all_chunks.values())[: top_k * 2]
    if not final_chunks:
        _enqueue_wiki_review_event(
            "qa_no_chunks",
            question=question,
            paper_ids=effective_paper_ids,
            wiki_context=wiki_context,
            reason="no_chunks",
            trace_id=trace_id,
            concept=_first_wiki_concept(wiki_context),
            paper_id=_first_paper_id(effective_paper_ids, []),
        )
        return _no_chunks_response(intent_cfg, trace, stopped, trace_id, wiki_context)

    # Stage 5 — abstain decision (after retrieve, before LLM, see ADR-0014).
    abstain_cfg = c.abstain
    abstain_result = _decide_abstain(final_chunks, abstain_cfg)
    if abstain_result["decision"] == abstain_mod.DECISION_NO_EVIDENCE:
        _enqueue_wiki_review_event(
            "qa_no_evidence",
            question=question,
            paper_ids=effective_paper_ids,
            chunks=final_chunks,
            wiki_context=wiki_context,
            reason="no_evidence",
            trace_id=trace_id,
            payload={"abstain": abstain_result},
            concept=_first_wiki_concept(wiki_context),
            paper_id=_first_paper_id(effective_paper_ids, final_chunks),
        )
        return _no_evidence_response(
            intent_cfg, trace, abstain_result, abstain_cfg, final_chunks, trace_id, wiki_context
        )
    if abstain_result["decision"] == abstain_mod.DECISION_WEAK:
        _enqueue_wiki_review_event(
            "qa_weak_evidence",
            question=question,
            paper_ids=effective_paper_ids,
            chunks=final_chunks,
            wiki_context=wiki_context,
            reason="weak_evidence",
            trace_id=trace_id,
            payload={"abstain": abstain_result},
            concept=_first_wiki_concept(wiki_context),
            paper_id=_first_paper_id(effective_paper_ids, final_chunks),
        )

    # Stage 6 — deterministic evidence selection + LLM call + citation cleanup.
    evidence_chunks, evidence_selection = select_evidence(
        question,
        final_chunks,
        intent=intent_cfg.get("intent"),
    )
    user = _build_user_prompt(question, evidence_chunks, abstain_result, wiki_context)
    try:
        raw = chat(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            temperature=cfg.load().llm.temperatures.answer,
            max_tokens=1024,
        )
    except Exception as e:
        log.warning(f"chat failed, returning evidence-only: {e}")
        return _chat_failed_response(
            intent_cfg,
            trace,
            stopped,
            final_chunks,
            evidence_chunks,
            evidence_selection,
            trace_id,
            e,
            wiki_context,
        )

    cleaned, valid = validate_citations(raw, evidence_chunks)
    suspicious = detect_suspicious_citations(cleaned)
    if suspicious["count"]:
        log.warning(f"suspicious citations detected: {suspicious}")
        cleaned = strip_suspicious_citation_forms(cleaned)
    log.info(
        f"qa_agentic done: trace_id={trace_id} iters={len(trace)} "
        f"stop={stopped} cites={len(valid)}"
    )
    counter("paper_rag_qa_total", {"intent": intent_cfg["intent"], "stop": stopped}).inc()
    counter("paper_rag_qa_citations_total").inc(len(valid))
    if suspicious["count"]:
        counter("paper_rag_qa_suspicious_total").inc(suspicious["count"])

    out = {
        "answer": cleaned,
        "citations": valid,
        "chunks": final_chunks,
        "evidence_chunks": evidence_chunks,
        "suspicious_citations": suspicious,
        "trace": {
            "intent": intent_cfg,
            "iters": trace,
            "stopped_by": stopped,
            "abstain": abstain_result,
            "evidence_selection": evidence_selection,
            "wiki_context": wiki_context,
            "trace_id": trace_id,
        },
    }
    if (user_id or "system") == "system":
        _store_in_cache(question_for_cache, effective_paper_ids, out)
    else:
        _store_in_cache(
            question_for_cache,
            effective_paper_ids,
            out,
            user_id=user_id,
        )
    return out
