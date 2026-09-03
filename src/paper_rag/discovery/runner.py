"""Orchestrator for the Paper Discovery Loop."""

from __future__ import annotations

from typing import Any

from ..ingest.dedup import normalize_title
from . import ranker, sources, store
from . import trace as trace_mod

DEFAULT_SOURCES = ["arxiv", "semantic_scholar"]


def run_discovery(
    topic: str,
    *,
    user_id: str = "system",
    source_names: list[str] | None = None,
    max_candidates: int = 10,
    search_limit: int = 25,
) -> dict[str, Any]:
    topic = " ".join(topic.split())
    if not topic:
        raise ValueError("topic is required")
    max_candidates = max(1, min(int(max_candidates), 20))
    search_limit = max(max_candidates, min(int(search_limit), 100))
    selected_sources = source_names or DEFAULT_SOURCES

    run_id = store.create_run(user_id, topic, selected_sources, max_candidates)
    trace = trace_mod.new_trace(topic, selected_sources, max_candidates)
    trace_mod.add_stage(trace, "search", sources=selected_sources, search_limit=search_limit)
    raw_candidates, source_errors = _search_sources(topic, selected_sources, search_limit)
    trace["source_errors"] = source_errors
    trace_mod.add_stage(trace, "normalize", raw_candidates=len(raw_candidates))

    ranked = ranker.rank_candidates(
        topic,
        _dedupe_candidates(raw_candidates),
        existing_keys=store.existing_paper_keys(),
        max_selected=max_candidates,
    )
    selected_count = sum(1 for item in ranked if item.get("selected"))
    trace_mod.add_stage(trace, "rank", candidates=len(ranked), selected=selected_count)

    stopped_by = _stopped_by(ranked, selected_count, max_candidates, source_errors)
    status = _status(ranked, selected_count, source_errors)
    store.save_candidates(run_id, ranked)
    trace_mod.add_stage(trace, "store", stored=len(ranked), stopped_by=stopped_by)
    store.finish_run(run_id, status=status, stopped_by=stopped_by, trace=trace)
    return store.get_run(run_id, user_id=user_id)


def ingest_candidate(candidate_id: int, *, user_id: str, force: bool = False) -> dict[str, Any]:
    candidate = store.get_candidate(candidate_id, user_id=user_id)
    existing = _existing_candidate(candidate)
    if existing and not force:
        result = {
            "candidate_id": candidate_id,
            "paper_id": existing,
            "status": "skipped",
            "reason": "already_indexed",
            "n_chunks": 0,
        }
        store.update_candidate_ingest(candidate_id, status="skipped", result=result)
        return result

    fetched = _fetch_candidate(candidate)
    _attach_user_id_to_fetch_meta(fetched, user_id)
    from ..store import ingest_pipeline

    result = ingest_pipeline.ingest(fetched, force=force)
    status = str(result.get("status") or "done")
    out = {
        "candidate_id": candidate_id,
        "paper_id": result.get("paper_id") or getattr(fetched.meta, "paper_id", candidate.get("paper_id")),
        "status": status,
        "reason": result.get("reason"),
        "merged_into": result.get("merged_into"),
        "n_chunks": int(result.get("chunks", result.get("n_chunks", 0)) or 0),
        "wiki": result.get("wiki") if isinstance(result.get("wiki"), dict) else None,
    }
    store.update_candidate_ingest(candidate_id, status=status, result=result)
    return out


def _search_sources(topic: str, source_names: list[str], limit: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source_name in source_names:
        try:
            candidates.extend(sources.search_source(source_name, topic, limit=limit))
        except Exception as exc:
            errors.append({"source": source_name, "error": str(exc)})
    return candidates, errors


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = (
            candidate.get("paper_id")
            or candidate.get("arxiv_id")
            or candidate.get("doi")
            or normalize_title(candidate.get("title") or "")
        )
        if not key or key in seen:
            continue
        seen.add(str(key))
        out.append(candidate)
    return out


def _stopped_by(
    ranked: list[dict[str, Any]],
    selected_count: int,
    max_candidates: int,
    source_errors: list[dict[str, str]],
) -> str:
    if not ranked and source_errors:
        return "source_errors"
    if not ranked:
        return "no_candidates"
    if selected_count >= max_candidates:
        return "selected_limit"
    return "search_exhausted"


def _status(
    ranked: list[dict[str, Any]],
    selected_count: int,
    source_errors: list[dict[str, str]],
) -> str:
    if not ranked and source_errors:
        return "degraded"
    if selected_count == 0 and source_errors:
        return "degraded"
    if source_errors:
        return "completed_with_warnings"
    return "completed"


def _existing_candidate(candidate: dict[str, Any]) -> str | None:
    keys = store.existing_paper_keys()
    for value in (
        candidate.get("paper_id"),
        candidate.get("arxiv_id"),
        f"arxiv:{candidate.get('arxiv_id')}" if candidate.get("arxiv_id") else None,
        candidate.get("doi"),
        f"doi:{candidate.get('doi')}" if candidate.get("doi") else None,
    ):
        if value and str(value) in keys:
            return str(candidate.get("paper_id") or value)
    return None


def _fetch_candidate(candidate: dict[str, Any]):
    if candidate.get("arxiv_id"):
        from ..ingest.arxiv_source import ArxivSource

        return ArxivSource().fetch(str(candidate["arxiv_id"]))
    if candidate.get("doi"):
        from ..ingest.semantic_scholar_source import SemanticScholarSource

        return SemanticScholarSource().fetch(f"doi:{candidate['doi']}")
    pdf_url = _first_pdf_url(candidate.get("urls") or [])
    if pdf_url:
        from ..ingest.url_source import UrlSource

        return UrlSource(title=candidate.get("title")).fetch(pdf_url)
    raise ValueError("candidate has no arxiv_id, doi, or PDF URL to ingest")


def _first_pdf_url(urls: list[str]) -> str | None:
    for url in urls:
        if ".pdf" in url.lower():
            return url
    return urls[0] if urls else None


def _attach_user_id_to_fetch_meta(fetched: Any, user_id: str) -> None:
    meta = getattr(fetched, "meta", None)
    if meta is None:
        return
    extra = getattr(meta, "extra", None)
    if not isinstance(extra, dict):
        extra = {}
        try:
            meta.extra = extra
        except (AttributeError, ValueError):
            return
    extra["user_id"] = user_id
