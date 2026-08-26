"""Claim-level answer recall primitives for RAG eval."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


def score_claims(
    *,
    answer: str,
    citation_ids: Iterable[str],
    expected_claims: Iterable[Any],
) -> dict:
    """Score expected claims against an answer and its cited chunks.

    Claim coverage is intentionally deterministic: labels provide accepted
    substrings or regexes. Grounding requires both coverage and at least one
    cited chunk listed in that claim's supporting chunks.
    """
    claims = [_claim_to_dict(claim) for claim in expected_claims]
    if not claims:
        return {
            "expected_claim_count": 0,
            "claim_recall": None,
            "grounded_claim_recall": None,
            "covered_claim_ids": [],
            "grounded_claim_ids": [],
            "missing_claims": [],
        }

    cites = set(citation_ids)
    covered_ids: list[str] = []
    grounded_ids: list[str] = []
    missing: list[dict] = []
    for claim in claims:
        claim_id = claim.get("id") or ""
        covered = _claim_matches(answer, claim)
        if covered:
            covered_ids.append(claim_id)
            supporting = set(claim.get("supporting_chunk_ids") or [])
            if supporting and supporting.intersection(cites):
                grounded_ids.append(claim_id)
        else:
            missing.append({"id": claim_id, "text": claim.get("text") or ""})

    total = len(claims)
    return {
        "expected_claim_count": total,
        "claim_recall": len(covered_ids) / total,
        "grounded_claim_recall": len(grounded_ids) / total,
        "covered_claim_ids": covered_ids,
        "grounded_claim_ids": grounded_ids,
        "missing_claims": missing,
    }


def _claim_matches(answer: str, claim: dict) -> bool:
    patterns = claim.get("accept_patterns") or []
    if not patterns and claim.get("text"):
        patterns = [claim["text"]]
    return any(_pattern_matches(answer, pattern) for pattern in patterns) or _text_overlap_matches(
        answer,
        claim.get("text") or "",
    )


def _pattern_matches(answer: str, pattern: str) -> bool:
    if not pattern:
        return False
    if pattern.startswith("re:"):
        try:
            return bool(re.search(pattern[3:], answer or "", flags=re.IGNORECASE))
        except re.error:
            return False
    return pattern.lower() in (answer or "").lower()


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "by", "for", "from", "how", "in", "is",
    "it", "of", "or", "that", "the", "this", "to", "what", "when", "why", "with",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _text_overlap_matches(answer: str, text: str) -> bool:
    claim_tokens = _content_tokens(text)
    if len(claim_tokens) < 2:
        return False
    answer_tokens = set(_content_tokens(answer))
    hits = sum(1 for token in claim_tokens if token in answer_tokens)
    return hits >= 2 and hits / len(claim_tokens) >= 0.5


def _content_tokens(text: str) -> list[str]:
    return [
        _stem_token(token)
        for token in _TOKEN_RE.findall((text or "").lower())
        if token not in _STOPWORDS
    ]


def _stem_token(token: str) -> str:
    if token.startswith("retriev"):
        return "retriev"
    if token.startswith("generat"):
        return "generat"
    if token.startswith("reflect"):
        return "reflect"
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _claim_to_dict(claim: Any) -> dict:
    if isinstance(claim, dict):
        return claim
    if hasattr(claim, "model_dump"):
        return claim.model_dump()
    return {
        "id": getattr(claim, "id", ""),
        "text": getattr(claim, "text", ""),
        "accept_patterns": getattr(claim, "accept_patterns", []),
        "supporting_chunk_ids": getattr(claim, "supporting_chunk_ids", []),
    }
