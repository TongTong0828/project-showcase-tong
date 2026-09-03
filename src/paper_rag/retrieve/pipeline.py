"""Shared retrieve+rerank+rewrite pipeline used by both qa_agentic and qa_stream.

Keeping it here avoids the previous copy-paste of ~12 lines per call site
and ensures both code paths stay in lock-step (e.g. when we swap the rerank
model or change the candidate window from top_k*3 to something else).
"""

from __future__ import annotations

from .hybrid import hybrid_search
from .rerank import rerank as _rerank

_MODALITY_HINTS = {
    "formula": (
        "formula", "equation", "latex", "derive", "derivation", "公式", "方程", "推导",
    ),
    "figure": (
        "figure", "fig.", "diagram", "plot", "image", "图", "图像", "图表", "示意图",
    ),
    "table": (
        "table", "tab.", "表", "表格", "对比表",
    ),
}
_MAX_CHUNKS_PER_PAPER = 2


def infer_modalities(query: str) -> list[str]:
    """Infer modality-specific retrieval hints from the user query."""
    q = query.lower()
    return [
        modality
        for modality, hints in _MODALITY_HINTS.items()
        if any(h in q for h in hints)
    ]


def retrieve_round_with_rewrite(
    query: str,
    paper_ids: list[str] | None,
    top_k: int,
    *,
    rewrite_fn=None,
    wiki_context: dict | None = None,
) -> tuple[list[dict], dict]:
    """One round of retrieval. Returns (reranked_chunks, rewrite_payload).

    ``rewrite_fn`` is injected so callers can swap in a stub during tests
    without monkey-patching the module-level rewrite. Defaults to
    ``paper_rag.rag.query_rewrite.rewrite``.
    """
    if rewrite_fn is None:
        from ..rag.query_rewrite import rewrite as rewrite_fn  # local import to avoid cycle

    try:
        rw = rewrite_fn(query, wiki_context=wiki_context)
    except TypeError as exc:
        if "wiki_context" not in str(exc):
            raise
        rw = rewrite_fn(query)
    modalities = infer_modalities(query)
    pooled: dict[str, dict] = {}
    for q in rw["dense_queries"]:
        search_specs = [(None, top_k)]
        search_specs.extend((modality, top_k) for modality in modalities)
        for modality, k in search_specs:
            hits = hybrid_search(q, top_k=k, paper_ids=paper_ids, modality=modality)
            for hit in hits:
                cid = hit.get("chunk_id")
                if not cid:
                    continue
                if cid not in pooled or hit.get("score_rrf", 0) > pooled[cid].get("score_rrf", 0):
                    pooled[cid] = hit
    candidates = list(pooled.values())
    candidates.sort(key=lambda x: x.get("score_rrf", 0), reverse=True)
    candidates = candidates[: top_k * 3]
    ranked = _rerank(query, candidates, top_k=top_k * 3)
    return _diversify_by_paper(ranked, top_k=top_k), rw


def retrieve_round(
    query: str,
    paper_ids: list[str] | None,
    top_k: int,
    *,
    wiki_context: dict | None = None,
) -> list[dict]:
    """Convenience wrapper that drops the rewrite payload."""
    chunks, _ = retrieve_round_with_rewrite(
        query, paper_ids, top_k, wiki_context=wiki_context
    )
    return chunks


def _diversify_by_paper(chunks: list[dict], *, top_k: int) -> list[dict]:
    """Keep strong results while preventing one paper from filling the window."""
    selected: list[dict] = []
    overflow: list[dict] = []
    counts: dict[str, int] = {}
    for chunk in chunks:
        paper_id = chunk.get("paper_id")
        if paper_id and counts.get(paper_id, 0) >= _MAX_CHUNKS_PER_PAPER:
            overflow.append(chunk)
            continue
        selected.append(chunk)
        if paper_id:
            counts[paper_id] = counts.get(paper_id, 0) + 1
        if len(selected) >= top_k:
            return selected[:top_k]

    for chunk in overflow:
        selected.append(chunk)
        if len(selected) >= top_k:
            break
    return selected[:top_k]


__all__ = ["infer_modalities", "retrieve_round", "retrieve_round_with_rewrite"]
