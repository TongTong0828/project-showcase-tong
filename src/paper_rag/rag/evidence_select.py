"""Deterministic evidence selection for QA generation.

Retrieval can return a broad inspection window. Before generation, select a
smaller set of chunks that the model is allowed to cite.
"""

from __future__ import annotations

import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "should",
    "that",
    "the",
    "this",
    "to",
    "use",
    "used",
    "uses",
    "using",
    "what",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "whose",
    "why",
    "with",
    "would",
}
_SECTION_HINTS = (
    "abstract",
    "introduction",
    "method",
    "approach",
    "experiment",
    "evaluation",
    "result",
    "conclusion",
)


def select_evidence(
    question: str,
    chunks: list[dict],
    *,
    intent: str | None = None,
    max_chunks: int = 4,
    max_per_paper: int = 2,
) -> tuple[list[dict], dict]:
    """Pick a compact, citable evidence set from retrieved chunks.

    The selector is deterministic: rerank/RRF score carries most of the weight,
    lexical overlap breaks ties, and section/title hints provide a tiny nudge.
    """
    if not chunks:
        return [], {
            "strategy": "deterministic_score_overlap",
            "selected_chunk_ids": [],
            "max_chunks": max_chunks,
            "max_per_paper": max_per_paper,
            "candidates": [],
        }

    scored = []
    for rank, chunk in enumerate(chunks, 1):
        features = _score_chunk(question, chunk, rank)
        scored.append((features["selection_score"], rank, chunk, features))
    scored.sort(key=lambda item: (-item[0], item[1]))

    selected: list[dict] = []
    counts: Counter[str] = Counter()
    for _, _, chunk, _ in scored:
        paper_id = str(chunk.get("paper_id") or "")
        if paper_id and counts[paper_id] >= max_per_paper:
            continue
        selected.append(chunk)
        if paper_id:
            counts[paper_id] += 1
        if len(selected) >= max_chunks:
            break

    trace = {
        "strategy": "deterministic_score_overlap",
        "intent": intent or "unknown",
        "max_chunks": max_chunks,
        "max_per_paper": max_per_paper,
        "input_chunk_ids": [c.get("chunk_id") for c in chunks if c.get("chunk_id")],
        "selected_chunk_ids": [c.get("chunk_id") for c in selected if c.get("chunk_id")],
        "candidates": [
            {
                "chunk_id": chunk.get("chunk_id"),
                "paper_id": chunk.get("paper_id"),
                "rank": rank,
                **features,
                "selected": chunk in selected,
            }
            for _, rank, chunk, features in scored
        ],
    }
    return selected, trace


def _score_chunk(question: str, chunk: dict, rank: int) -> dict:
    text = " ".join(
        str(chunk.get(key) or "")
        for key in ("title", "section", "text", "raw_snippet")
    )
    overlap = _lexical_overlap(question, text)
    model_score = _model_score(chunk)
    section_hint = _section_hint(chunk)
    rank_bonus = 1.0 / max(rank, 1)
    selection_score = model_score + 0.2 * overlap + 0.03 * section_hint + 0.001 * rank_bonus
    return {
        "selection_score": round(selection_score, 6),
        "model_score": round(model_score, 6),
        "lexical_overlap": round(overlap, 6),
        "section_hint": section_hint,
    }


def _model_score(chunk: dict) -> float:
    for key in ("score_rerank", "score_rrf", "score_dense", "score"):
        value = chunk.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _lexical_overlap(question: str, text: str) -> float:
    q_tokens = _content_tokens(question)
    if not q_tokens:
        return 0.0
    text_tokens = _content_tokens(text)
    return len(q_tokens & text_tokens) / len(q_tokens)


def _content_tokens(text: str) -> set[str]:
    tokens = set(_TOKEN_RE.findall(text.lower()))
    filtered = {token for token in tokens if token not in _STOPWORDS}
    return filtered or tokens


def _section_hint(chunk: dict) -> int:
    section = str(chunk.get("section") or "").lower()
    title = str(chunk.get("title") or "").lower()
    haystack = f"{section} {title}"
    return int(any(hint in haystack for hint in _SECTION_HINTS))


__all__ = ["select_evidence"]
