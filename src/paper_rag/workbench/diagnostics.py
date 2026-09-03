from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from paper_rag import config as cfg

from .credentials import credential_status
from .read_store import WorkbenchReadStore
from .settings import WorkbenchSettings


def build_index_health(
    settings: WorkbenchSettings,
    *,
    read_store: WorkbenchReadStore | None = None,
) -> dict[str, Any]:
    store = read_store or WorkbenchReadStore()
    sqlite_summary, quality = _sqlite_summary(store)
    qdrant = _qdrant_summary(cfg.load())
    credentials = credential_status(credentials_path=settings.credentials_path).as_dict()
    llm = {
        "configured": bool(
            settings.openai_base_url
            and settings.chat_model
            and credentials["configured"]
        ),
        "chat_model": settings.chat_model,
        "base_url_host": urlparse(settings.openai_base_url).netloc or None,
        "credential_source": credentials["source"],
    }
    retrieval = {
        "dense_available": bool(qdrant["reachable"]),
        "sparse_available": bool(sqlite_summary["available"]),
        "hybrid_available": bool(sqlite_summary["available"]),
    }
    warnings = _warnings(sqlite_summary, qdrant, llm, quality)
    return {
        "status": _overall_status(sqlite_summary, qdrant, llm),
        "sqlite": sqlite_summary,
        "qdrant": qdrant,
        "retrieval": retrieval,
        "llm": llm,
        "corpus_quality": quality,
        "warnings": warnings,
    }


def _sqlite_summary(store: WorkbenchReadStore) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        quality = store.corpus_quality()
    except Exception as exc:  # noqa: BLE001
        return (
            {
                "available": False,
                "paper_count": 0,
                "chunk_count": 0,
                "fts_available": False,
                "degraded_reason": type(exc).__name__,
            },
            {
                "paper_count": 0,
                "chunk_count": 0,
                "duplicate_chunk_count": 0,
                "parser_artifact_count": 0,
                "missing_section_count": 0,
                "samples": [],
            },
        )
    return (
        {
            "available": True,
            "paper_count": int(quality.get("paper_count", 0)),
            "chunk_count": int(quality.get("chunk_count", 0)),
            "fts_available": True,
        },
        quality,
    )


def _qdrant_summary(config: Any) -> dict[str, Any]:
    qdrant = config.qdrant
    url = str(qdrant.url or "")
    local_path = getattr(qdrant, "local_path", None)
    if local_path or url.startswith(("file://", "local://")):
        mode = "embedded"
    elif url:
        mode = "server"
    else:
        mode = "none"

    reachable = False
    degraded_reason = None
    try:
        from paper_rag.store.qdrant_store import get_client

        client = get_client()
        client.get_collections()
        reachable = True
    except Exception as exc:  # noqa: BLE001
        degraded_reason = type(exc).__name__

    return {
        "configured": bool(url or local_path),
        "mode": mode,
        "reachable": reachable,
        "collection_chunks": qdrant.collection_chunks,
        "degraded_reason": degraded_reason,
    }


def _overall_status(
    sqlite_summary: dict[str, Any],
    qdrant: dict[str, Any],
    llm: dict[str, Any],
) -> str:
    if not sqlite_summary["available"] or not llm["configured"]:
        return "blocked"
    if not qdrant["reachable"]:
        return "degraded"
    return "healthy"


def _warnings(
    sqlite_summary: dict[str, Any],
    qdrant: dict[str, Any],
    llm: dict[str, Any],
    quality: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if not sqlite_summary["available"]:
        warnings.append("SQLite corpus is unavailable.")
    if not qdrant["reachable"]:
        warnings.append("Dense retrieval is unavailable; sparse fallback is active.")
    if quality["duplicate_chunk_count"]:
        warnings.append("Duplicate chunks detected in the corpus.")
    if quality["parser_artifact_count"]:
        warnings.append("Parser artifacts detected in indexed chunks.")
    if not llm["configured"]:
        warnings.append("LLM generation is not configured.")
    return warnings
