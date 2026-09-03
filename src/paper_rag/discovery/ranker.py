"""Candidate ranking for the Paper Discovery Loop."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9-]{1,}")
_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "for",
    "from",
    "how",
    "into",
    "of",
    "on",
    "paper",
    "papers",
    "the",
    "this",
    "to",
    "using",
    "with",
}
_SOURCE_CONFIDENCE = {"arxiv": 0.15, "semantic_scholar": 0.12, "s2": 0.12}
_LOW_RELEVANCE_THRESHOLD = 0.12


def rank_candidates(
    topic: str,
    candidates: list[dict[str, Any]],
    *,
    existing_keys: set[str] | None = None,
    max_selected: int = 10,
) -> list[dict[str, Any]]:
    """Rank candidates and attach score, reasons, and skip decisions."""
    existing_keys = existing_keys or set()
    topic_terms = _terms(topic)
    scored: list[dict[str, Any]] = []
    for raw in candidates:
        item = dict(raw)
        for key in ("paper_id", "title", "abstract", "arxiv_id", "doi", "urls", "authors", "year"):
            item.setdefault(key, None)
        score, parts = _score_candidate(topic_terms, item)
        item["score"] = round(score, 4)
        item["rank_reason"] = "; ".join(parts)
        item["selected"] = False
        item["skip_reason"] = None
        if _is_existing(item, existing_keys):
            item["skip_reason"] = "already_indexed"
            item["rank_reason"] += "; dedup_penalty=-0.40"
            item["score"] = round(max(0.0, item["score"] - 0.4), 4)
        scored.append(item)

    scored.sort(
        key=lambda item: (item.get("skip_reason") is None, item.get("score", 0.0)),
        reverse=True,
    )
    selected_count = 0
    for rank, item in enumerate(scored, start=1):
        item["rank"] = rank
        if item.get("skip_reason"):
            continue
        if item["score"] < _LOW_RELEVANCE_THRESHOLD:
            item["skip_reason"] = "low_relevance"
            continue
        if selected_count >= max_selected:
            item["skip_reason"] = "below_selection_cutoff"
            continue
        item["selected"] = True
        selected_count += 1
    return scored


def _score_candidate(topic_terms: set[str], item: dict[str, Any]) -> tuple[float, list[str]]:
    title_terms = _terms(str(item.get("title") or ""))
    abstract_terms = _terms(str(item.get("abstract") or ""))
    candidate_terms = title_terms | abstract_terms
    overlap = len(topic_terms & candidate_terms) / max(1, len(topic_terms))
    title_overlap = len(topic_terms & title_terms) / max(1, len(topic_terms))
    year_bonus = _recency_bonus(item.get("year"))
    source_confidence = _SOURCE_CONFIDENCE.get(str(item.get("source") or ""), 0.08)
    abstract_bonus = 0.08 if len(abstract_terms) >= 12 else 0.0
    score = min(
        1.0,
        overlap * 0.5 + title_overlap * 0.18 + year_bonus + source_confidence + abstract_bonus,
    )
    return score, [
        f"keyword_overlap={overlap:.2f}",
        f"title_overlap={title_overlap:.2f}",
        f"recency={year_bonus:.2f}",
        f"source_confidence={source_confidence:.2f}",
        f"abstract_bonus={abstract_bonus:.2f}",
    ]


def _terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in _WORD_RE.findall(text)
        if token.lower() not in _STOPWORDS and len(token) > 2
    }


def _recency_bonus(year: Any) -> float:
    try:
        y = int(year)
    except (TypeError, ValueError):
        return 0.0
    current_year = datetime.utcnow().year
    if y >= current_year - 1:
        return 0.12
    if y >= current_year - 3:
        return 0.08
    if y >= current_year - 6:
        return 0.04
    return 0.0


def _is_existing(item: dict[str, Any], existing_keys: set[str]) -> bool:
    keys = {
        str(value)
        for value in (
            item.get("paper_id"),
            item.get("arxiv_id"),
            f"arxiv:{item.get('arxiv_id')}" if item.get("arxiv_id") else None,
            item.get("doi"),
            f"doi:{item.get('doi')}" if item.get("doi") else None,
        )
        if value
    }
    return bool(keys & existing_keys)
