"""Metric primitives — pure functions, no IO, easy to unit-test."""

from __future__ import annotations

from collections.abc import Iterable
from math import log2


def recall_at_k(predicted: Iterable[str], relevant: Iterable[str], k: int) -> float:
    """paper-level or chunk-level recall@k.

    Both inputs deduplicated; k applied to predicted (preserves order).
    Returns 0.0 if `relevant` is empty.
    """
    rel = list(dict.fromkeys(relevant))
    if not rel:
        return 0.0
    pred = list(dict.fromkeys(predicted))[:k]
    hit = sum(1 for r in rel if r in pred)
    return hit / len(rel)


def precision_at_k(predicted: Iterable[str], relevant: Iterable[str], k: int) -> float:
    rel_set = set(relevant)
    if not rel_set:
        return 0.0
    pred = list(dict.fromkeys(predicted))[:k]
    if not pred:
        return 0.0
    return sum(1 for p in pred if p in rel_set) / len(pred)


def mrr(predicted: Iterable[str], relevant: Iterable[str]) -> float:
    """Mean reciprocal rank of the FIRST relevant hit. Single-query MRR."""
    rel_set = set(relevant)
    for i, p in enumerate(dict.fromkeys(predicted), 1):
        if p in rel_set:
            return 1.0 / i
    return 0.0


def ndcg_at_k(predicted: Iterable[str], relevant: Iterable[str], k: int) -> float | None:
    """Binary nDCG@k over ids.

    Returns None when there is no relevance label, so callers can report the
    metric as skipped instead of pretending the system scored 0.0.
    """
    rel_set = set(relevant)
    if not rel_set:
        return None
    pred = list(dict.fromkeys(predicted))[:k]
    dcg = 0.0
    for i, p in enumerate(pred, 1):
        if p in rel_set:
            dcg += 1.0 / log2(i + 1)
    ideal_hits = min(len(rel_set), k)
    idcg = sum(1.0 / log2(i + 1) for i in range(1, ideal_hits + 1))
    return round(dcg / idcg, 3) if idcg else 0.0


def citation_precision(citations: Iterable[str], relevant_chunk_ids: Iterable[str]) -> float | None:
    """Among cited chunk_ids, fraction that are in ground-truth relevant set.

    Returns None when ground-truth chunk-level not provided (caller should
    skip this metric in aggregation rather than count it as 0).
    """
    rel_set = set(relevant_chunk_ids)
    if not rel_set:
        return None
    cites = list(dict.fromkeys(citations))
    if not cites:
        return None
    return sum(1 for c in cites if c in rel_set) / len(cites)


def citation_recall(citations: Iterable[str], relevant_chunk_ids: Iterable[str]) -> float | None:
    """Among ground-truth chunks, fraction cited by the answer."""
    rel = list(dict.fromkeys(relevant_chunk_ids))
    if not rel:
        return None
    cites = set(citations)
    return sum(1 for c in rel if c in cites) / len(rel)


def citation_paper_precision(
    citation_paper_ids: Iterable[str | None],
    relevant_paper_ids: Iterable[str],
) -> float | None:
    """Among cited chunks, fraction whose paper is relevant.

    Returns None when there is no paper-level label. Empty citations are
    treated as 1.0: the answer did not cite a wrong paper.
    """
    rel_set = set(relevant_paper_ids)
    if not rel_set:
        return None
    cited = list(citation_paper_ids)
    if not cited:
        return 1.0
    return sum(1 for paper_id in cited if paper_id in rel_set) / len(cited)


def citation_existence_rate(citations: Iterable[str], retrieved_chunk_ids: Iterable[str]) -> float:
    """Cheap proxy when no chunk-level GT: fraction of citations that exist
    in the retrieved set (i.e., not hallucinated). qa_simple/qa_agentic
    already cleans these, so this should always be 1.0 unless the model
    fabricated formatted ids that happened to match the regex but don't
    exist."""
    ret = set(retrieved_chunk_ids)
    cites = list(dict.fromkeys(citations))
    if not cites:
        return 1.0
    return sum(1 for c in cites if c in ret) / len(cites)


def must_contain_score(answer: str, needles: Iterable[str]) -> float:
    needles = [n for n in needles if n]
    if not needles:
        return 1.0
    low = (answer or "").lower()
    return sum(1 for n in needles if n.lower() in low) / len(needles)


def must_not_contain_violations(answer: str, needles: Iterable[str]) -> int:
    low = (answer or "").lower()
    return sum(1 for n in needles if n and n.lower() in low)


def false_positive_rate(predicted: Iterable[str], irrelevant: Iterable[str], k: int) -> float | None:
    """Fraction of `irrelevant` papers that leak into predicted top-k.

    Returns None when no irrelevant set is supplied (aggregator skips).
    Lower is better; 0.0 means no false positives.
    """
    irrel = list(dict.fromkeys(irrelevant))
    if not irrel:
        return None
    pred = set(list(dict.fromkeys(predicted))[:k])
    return sum(1 for r in irrel if r in pred) / len(irrel)
