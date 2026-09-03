"""paper_search tool entry returning paper-level matches from indexed chunks."""

from __future__ import annotations

from collections import defaultdict

from ..retrieve.dense import retrieve
from ..retrieve.hybrid import hybrid_search
from ._schema import PaperSearchInput


def paper_search(input: PaperSearchInput) -> list[dict]:
    chunks = retrieve(input.query, top_k=input.top_k * 4)
    if not chunks:
        chunks = hybrid_search(input.query, top_k=input.top_k * 2)
    by_paper: dict[str, dict] = {}
    best: dict[str, float] = defaultdict(lambda: -1.0)
    for c in chunks:
        pid = c.get("paper_id")
        if not pid:
            continue
        score = _score(c)
        if score > best[pid]:
            best[pid] = score
            by_paper[pid] = {
                "chunk_id": c.get("chunk_id"),
                "paper_id": pid,
                "title": c.get("title"),
                "section": c.get("section"),
                "snippet": (c.get("text") or "")[:280],
                "score": score,
            }
    ranked = sorted(by_paper.values(), key=lambda x: x["score"], reverse=True)
    return ranked[: input.top_k]


def _score(chunk: dict) -> float:
    for key in ("score", "score_dense", "score_rrf", "score_bm25"):
        value = chunk.get(key)
        if isinstance(value, int | float):
            return float(value)
    return 0.0


__all__ = [
    "paper_search",
]
