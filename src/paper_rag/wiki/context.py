"""Read-only wiki context used by QA as background, never as evidence."""

from __future__ import annotations

import re
from typing import Any

from ..utils.logger import get_logger
from . import store as wstore
from .schema import WikiEntry, normalize_name

log = get_logger("wiki.context")

_ROLE = "background_not_evidence"
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")
_STOPWORDS = {
    "and",
    "are",
    "for",
    "from",
    "into",
    "learn",
    "learns",
    "learning",
    "method",
    "paper",
    "representation",
    "representations",
    "that",
    "the",
    "this",
    "with",
}


def _empty_context() -> dict[str, Any]:
    return {"role": _ROLE, "fingerprint": "", "entries": []}


def _entry_to_context(entry: WikiEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "name": entry.name,
        "category": entry.category,
        "definition": entry.definition,
        "aliases": list(entry.aliases or [])[:5],
        "key_papers": list(entry.key_papers or [])[:8],
        "evidence_chunks": list(entry.evidence_chunks or [])[:8],
        "version": int(entry.version or 1),
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


def _fingerprint(entries: list[dict[str, Any]]) -> str:
    pairs = [f"{e.get('entry_id')}:{int(e.get('version') or 1)}" for e in entries]
    return "|".join(sorted(pairs))


def _norm_contains(haystack: str, needle: str) -> bool:
    n = normalize_name(needle or "")
    return bool(n and n in haystack)


def _score_entry(entry: WikiEntry, question_norm: str, paper_set: set[str]) -> int:
    score = 0
    if _norm_contains(question_norm, entry.name):
        score += 100
    for alias in entry.aliases or []:
        if _norm_contains(question_norm, alias):
            score += 90
            break
    overlap = paper_set.intersection(entry.key_papers or [])
    if overlap:
        score += 50 + min(len(overlap), 3)
    return score


def resolve_wiki_context(
    question: str,
    paper_ids: list[str] | None = None,
    max_entries: int = 3,
) -> dict[str, Any]:
    """Return compact wiki background context for a QA question.

    Failures are intentionally non-fatal: wiki can help route and explain, but
    the evidence contract belongs to retrieved chunks.
    """
    try:
        entries = wstore.list_all()
    except Exception as e:
        log.warning(f"wiki context skipped: {e}")
        return _empty_context()
    if not entries:
        return _empty_context()

    question_norm = normalize_name(question or "")
    paper_set = {str(pid) for pid in (paper_ids or []) if pid}
    scored: list[tuple[int, WikiEntry]] = []
    for entry in entries:
        score = _score_entry(entry, question_norm, paper_set)
        if score > 0:
            scored.append((score, entry))

    if not scored:
        try:
            from .normalize import find_match

            matched = find_match(question, embed_query=True)
            if matched:
                entry = wstore.get_entry(matched)
                if entry:
                    scored.append((25, entry))
        except Exception as e:
            log.debug(f"wiki semantic context skipped: {e}")

    scored.sort(key=lambda item: (-item[0], item[1].entry_id))
    compact = [_entry_to_context(entry) for _, entry in scored[:max_entries]]
    return {"role": _ROLE, "fingerprint": _fingerprint(compact), "entries": compact}


def format_wiki_background(context: dict[str, Any]) -> str:
    entries = list((context or {}).get("entries") or [])
    if not entries:
        return ""
    blocks = [
        "Wiki background (not evidence). Do not cite this background. "
        "Use it only to interpret terms, aliases, and likely related papers. "
        "If it conflicts with evidence chunks, evidence chunks win."
    ]
    for entry in entries:
        aliases = ", ".join(entry.get("aliases") or [])
        key_papers = ", ".join(entry.get("key_papers") or [])
        line = f"- {entry.get('name')} (v{entry.get('version', 1)}): {entry.get('definition', '')}".strip()
        if aliases:
            line += f"\n  aliases: {aliases}"
        if key_papers:
            line += f"\n  key_papers: {key_papers}"
        blocks.append(line)
    return "\n".join(blocks)


def _definition_phrases(definition: str) -> list[str]:
    words = [
        w.lower()
        for w in _WORD_RE.findall(definition or "")
        if w.lower() not in _STOPWORDS
    ]
    if not words:
        return []
    phrases = [" ".join(words[:6])]
    if len(words) >= 3:
        phrases.append(" ".join(words[-3:]))
    return [p for p in dict.fromkeys(phrases) if p]


def wiki_rewrite_hints(context: dict[str, Any]) -> dict[str, Any]:
    dense: list[str] = []
    bm25_terms: list[str] = []
    key_papers: list[str] = []
    for entry in (context or {}).get("entries") or []:
        name = (entry.get("name") or "").strip()
        if name:
            dense.append(name)
            bm25_terms.append(name.lower())
        for alias in entry.get("aliases") or []:
            if alias:
                dense.append(str(alias))
        for phrase in _definition_phrases(entry.get("definition") or ""):
            dense.append(phrase)
            bm25_terms.append(phrase)
        for paper_id in entry.get("key_papers") or []:
            if paper_id:
                key_papers.append(str(paper_id))

    dense = list(dict.fromkeys(dense))[:12]
    key_papers = list(dict.fromkeys(key_papers))[:8]
    return {
        "dense_queries": dense,
        "bm25_query": " ".join(dict.fromkeys(bm25_terms)),
        "key_papers": key_papers,
    }


__all__ = ["format_wiki_background", "resolve_wiki_context", "wiki_rewrite_hints"]
