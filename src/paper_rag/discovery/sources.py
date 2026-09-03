"""Search adapters for paper discovery."""

from __future__ import annotations

from typing import Any

import httpx

from ..utils.ids import make_paper_id, normalize_arxiv, normalize_doi

_S2_BASE = "https://api.semanticscholar.org/graph/v1"
_S2_FIELDS = "title,authors,year,venue,abstract,externalIds,openAccessPdf,url"


def normalize_candidate(raw: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Normalize source-specific paper metadata into a discovery candidate."""
    title = " ".join(str(raw.get("title") or "").split())
    abstract = " ".join(str(raw.get("abstract") or raw.get("summary") or "").split())
    arxiv_id = normalize_arxiv(str(raw.get("arxiv_id") or raw.get("arxivId") or ""))
    doi = normalize_doi(str(raw.get("doi") or raw.get("DOI") or ""))
    urls = [str(url) for url in (raw.get("urls") or []) if url]
    if raw.get("url"):
        urls.append(str(raw["url"]))
    if raw.get("pdf_url"):
        urls.append(str(raw["pdf_url"]))
    urls = _dedupe(urls)

    paper_id = raw.get("paper_id")
    if not paper_id:
        try:
            paper_id = make_paper_id(arxiv_id=arxiv_id, doi=doi)
        except ValueError:
            source_id = raw.get("source_id") or raw.get("paperId") or _slug(title)
            paper_id = f"{source}:{source_id}"

    authors = raw.get("authors") or []
    if authors and isinstance(authors[0], dict):
        authors = [item.get("name") for item in authors if item.get("name")]

    return {
        "source": source,
        "source_id": raw.get("source_id") or raw.get("paperId") or raw.get("entry_id"),
        "paper_id": str(paper_id),
        "title": title,
        "abstract": abstract,
        "authors": [str(author) for author in authors if author],
        "year": _coerce_int(raw.get("year")),
        "venue": raw.get("venue"),
        "doi": doi,
        "arxiv_id": arxiv_id,
        "urls": urls,
    }


def search_source(name: str, topic: str, *, limit: int = 25) -> list[dict[str, Any]]:
    if name == "arxiv":
        return search_arxiv(topic, limit=limit)
    if name in {"semantic_scholar", "s2"}:
        return search_semantic_scholar(topic, limit=limit)
    raise ValueError(f"unknown discovery source: {name}")


def search_arxiv(topic: str, *, limit: int = 25) -> list[dict[str, Any]]:
    try:
        import arxiv
    except ImportError as exc:
        raise RuntimeError("arxiv package not installed. Run: pip install arxiv") from exc

    client = arxiv.Client(page_size=min(limit, 100), delay_seconds=3, num_retries=3)
    search = arxiv.Search(
        query=topic,
        max_results=limit,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    out: list[dict[str, Any]] = []
    for result in client.results(search):
        out.append(
            normalize_candidate(
                {
                    "source_id": getattr(result, "entry_id", None),
                    "title": getattr(result, "title", ""),
                    "summary": getattr(result, "summary", ""),
                    "authors": [author.name for author in getattr(result, "authors", [])],
                    "year": getattr(getattr(result, "published", None), "year", None),
                    "doi": getattr(result, "doi", None),
                    "arxiv_id": normalize_arxiv(getattr(result, "entry_id", "")),
                    "urls": [
                        url
                        for url in (
                            getattr(result, "entry_id", None),
                            getattr(result, "pdf_url", None),
                        )
                        if url
                    ],
                },
                source="arxiv",
            )
        )
    return out


def search_semantic_scholar(topic: str, *, limit: int = 25, api_key: str | None = None) -> list[dict[str, Any]]:
    headers = {"User-Agent": "paper-rag/0.1"}
    if api_key:
        headers["x-api-key"] = api_key
    with httpx.Client(timeout=30, headers=headers) as client:
        response = client.get(
            f"{_S2_BASE}/paper/search",
            params={"query": topic, "limit": min(limit, 100), "fields": _S2_FIELDS},
        )
        response.raise_for_status()
        data = response.json()

    out: list[dict[str, Any]] = []
    for item in data.get("data") or []:
        ext = item.get("externalIds") or {}
        pdf_url = (item.get("openAccessPdf") or {}).get("url")
        out.append(
            normalize_candidate(
                {
                    "source_id": item.get("paperId"),
                    "title": item.get("title"),
                    "abstract": item.get("abstract"),
                    "authors": item.get("authors") or [],
                    "year": item.get("year"),
                    "venue": item.get("venue"),
                    "doi": ext.get("DOI"),
                    "arxiv_id": ext.get("ArXiv"),
                    "url": item.get("url"),
                    "pdf_url": pdf_url,
                    "paperId": item.get("paperId"),
                },
                source="semantic_scholar",
            )
        )
    return out


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _slug(value: str) -> str:
    slug = "-".join(value.lower().split())[:80]
    return slug or "unknown"
