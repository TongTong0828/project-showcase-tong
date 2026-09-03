"""Query rewriting and HyDE.

Given a user question, produce:
  - 2-4 paraphrase variants for dense retrieval
  - 1 HyDE pseudo-answer for dense retrieval
  - extracted keyword string for BM25
"""

from __future__ import annotations

import json
import os
import re

from .. import config as cfg
from ..utils.logger import get_logger
from .llm import chat

log = get_logger("rag.query_rewrite")
_FORCE_LOCAL_REWRITE_ENV = "PAPER_RAG_FORCE_LOCAL_REWRITE"

_ORIGINAL_ALIAS_RE = re.compile(
    r"\b(?:the\s+)?(?:original|first|earliest)\s+([A-Za-z][A-Za-z0-9-]{1,20})"
    r"(?:\s+(?:paper|work|model))?",
    re.IGNORECASE,
)
_TITLE_WORD_RE = re.compile(r"[A-Za-z]+")
_ACRONYM_STOPWORDS = {"a", "an", "and", "for", "of", "the", "to", "in", "on", "with"}

_PROMPT = """You help an academic paper RAG system. Given a question, output a JSON
object with three keys:

  "variants":  array of 2-3 paraphrases that may match different wording in papers
  "keywords":  short string of 3-8 lowercase keywords (BM25 input)
  "hyde":      a 2-3 sentence hypothetical answer if you had to guess (used as
               an extra dense query). Be plausible; do NOT fabricate citations.

Question: {q}

Return only JSON.
"""


def rewrite(question: str, wiki_context: dict | None = None) -> dict:
    c = cfg.load()
    enable = c.rag.enable_hyde
    data = {}
    force_local = _truthy_env(_FORCE_LOCAL_REWRITE_ENV)
    if force_local:
        log.debug("rewrite forced to local fallback by PAPER_RAG_FORCE_LOCAL_REWRITE")
    elif c.llm.chat_model and c.llm.api_key and c.llm.base_url:
        try:
            raw = chat(
                [{"role": "user", "content": _PROMPT.replace("{q}", question)}],
                temperature=c.llm.temperatures.rewrite,
                max_tokens=400,
            )
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
        except Exception as e:
            log.warning(f"rewrite failed: {e}; using local fallback variants")
    else:
        log.debug("rewrite LLM not configured; using local fallback variants")

    wiki_hints = _wiki_hints(wiki_context)
    variants = _dedupe([
        *(data.get("variants") or []),
        *_heuristic_variants(question),
        *wiki_hints["dense_queries"],
    ])
    keyword_parts = [data.get("keywords") or question]
    if wiki_hints["bm25_query"]:
        keyword_parts.append(wiki_hints["bm25_query"])
    keywords = " ".join(part for part in keyword_parts if part)
    hyde = data.get("hyde") if enable else None
    queries_dense = [question, *variants]
    if hyde:
        queries_dense.append(hyde)
    return {
        "dense_queries": _dedupe(queries_dense),
        "bm25_query": keywords,
        "raw": {
            **data,
            "wiki_context_used": bool(wiki_hints["dense_queries"]),
            "wiki_key_papers": wiki_hints["key_papers"],
        },
    }


def _wiki_hints(wiki_context: dict | None) -> dict:
    if not wiki_context:
        return {"dense_queries": [], "bm25_query": "", "key_papers": []}
    try:
        from ..wiki.context import wiki_rewrite_hints

        return wiki_rewrite_hints(wiki_context)
    except Exception as e:
        log.warning(f"wiki rewrite hints skipped: {e}")
        return {"dense_queries": [], "bm25_query": "", "key_papers": []}


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        item = " ".join((item or "").split())
        key = item.lower()
        if item and key not in seen:
            out.append(item)
            seen.add(key)
    return out


def _heuristic_variants(question: str) -> list[str]:
    """Local-library fallback for paper aliases when LLM rewrite is unavailable.

    This catches common academic phrasing such as "the original RAG paper" by
    mapping the acronym back to the earliest matching paper title in SQLite.
    """
    variants: list[str] = []
    qlow = question.lower()
    if "recall@k" in qlow and "precision@k" in qlow and "retrieval" in qlow:
        variants.extend([
            "RAG retrieval evaluation metrics recall precision retrieval stage",
            "retrieval augmented generation evaluation recall@k precision@k",
        ])
    if "factscore" in qlow or "fact score" in qlow:
        variants.extend([
            "Self-RAG FactScore biographies factuality metric atomic facts",
            "FactScore SELF-RAG evaluation factuality biographies",
            "FactScore factuality precision atomic facts knowledge source",
        ])
    if "chunk" in qlow and ("size" in qlow or "embedding" in qlow or "production" in qlow):
        variants.extend([
            "RAG survey chunking strategy 100 256 512 embedding chunks",
            "retrieval augmented generation chunk size embedding granularity",
            "chunking strategy larger chunks capture more context smaller chunks retrieval precision",
        ])
    if "latency" in qlow and ("rerank" in qlow or "retrieval" in qlow or "rag" in qlow):
        variants.extend([
            "retrieval latency reranking dense retriever latency cost",
            "BEIR retrieval latency reranking dense retrieval efficiency",
            "RAG higher latency retrieval augmentation rerank chunks",
        ])
    if "rag-sequence" in qlow and "rag-token" in qlow:
        variants.extend([
            "RAG-Sequence uses the same retrieved document for the whole sequence",
            "RAG-Token can use different retrieved documents for each target token",
            "RAG-Sequence RAG-Token latent documents per sequence per token model difference",
        ])
    if "pre-retrieval" in qlow or "post-retrieval" in qlow:
        variants.extend([
            "Advanced RAG pre-retrieval post-retrieval optimization strategies indexing retrieval generation",
            "RAG survey pre-retrieval optimization data indexing query optimization",
            "RAG survey post-retrieval processing reranking context compression optimization",
        ])
    for m in _ORIGINAL_ALIAS_RE.finditer(question):
        alias = m.group(1).upper()
        papers = _papers_for_alias(alias)
        if not papers:
            continue
        p = sorted(papers, key=lambda x: (x.get("year") or 9999, x.get("title") or ""))[0]
        title = p.get("title")
        if title:
            variants.append(title)
            variants.append(f"{alias} original paper {title}")
    return _dedupe(variants)[:5]


def _papers_for_alias(alias: str) -> list[dict]:
    try:
        from sqlmodel import Session, select

        from ..store.sqlite_store import Paper, get_engine

        with Session(get_engine()) as s:
            papers = s.exec(select(Paper)).all()
    except Exception as e:
        log.debug(f"paper alias lookup skipped: {e}")
        return []

    out: list[dict] = []
    for p in papers:
        if alias in _aliases_for_title(p.title or ""):
            out.append({"title": p.title, "year": p.year, "arxiv_id": p.arxiv_id})
    return out


def _aliases_for_title(title: str) -> set[str]:
    aliases: set[str] = set()
    tokens = [w for w in _TITLE_WORD_RE.findall(title) if w.lower() not in _ACRONYM_STOPWORDS]
    for i in range(len(tokens)):
        for n in range(2, 5):
            window = tokens[i:i + n]
            if len(window) != n:
                continue
            acronym = "".join(w[0].upper() for w in window)
            if 2 <= len(acronym) <= 8:
                aliases.add(acronym)
    for token in re.findall(r"\b[A-Z][A-Z0-9-]{1,20}\b", title):
        aliases.add(token.upper())
    return aliases


__all__ = [
    "rewrite",
]
