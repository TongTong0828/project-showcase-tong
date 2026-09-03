"""Paper ingest tool facade.

This module is the stable outer adapter used by MCP tools and proactive
auto-ingest hooks. It keeps source selection here and delegates the heavy work
to ``store.ingest_pipeline``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .. import config as cfg
from ..utils.paths import ensure_dirs


class PaperIngestInput(BaseModel):
    arxiv_id: str | None = Field(default=None, description="arXiv id, e.g. 2310.11511")
    pdf_url: str | None = Field(default=None, description="Direct PDF URL")
    pdf_path: str | None = Field(default=None, description="Local PDF path")
    title_hint: str | None = Field(default=None, description="Optional title hint")
    user_id: str | None = Field(default=None, description="Owner user id")
    force: bool = Field(default=False, description="Re-ingest even when already done")


def ingest(payload: PaperIngestInput | dict[str, Any]) -> dict[str, Any]:
    """Fetch and index one paper from arXiv, a PDF URL, or a local PDF path."""
    body = payload if isinstance(payload, PaperIngestInput) else PaperIngestInput(**payload)
    if not (body.arxiv_id or body.pdf_url or body.pdf_path):
        raise ValueError("Provide one of arxiv_id, pdf_url, or pdf_path")

    ensure_dirs()

    if body.arxiv_id:
        from ..ingest.arxiv_source import ArxivSource

        fetched = ArxivSource().fetch(body.arxiv_id)
    elif body.pdf_url:
        from ..ingest.url_source import UrlSource

        fetched = UrlSource(title=body.title_hint).fetch(body.pdf_url)
    else:
        from ..ingest.local_source import LocalSource

        fetched = LocalSource(title=body.title_hint).fetch(body.pdf_path or "")

    if body.user_id:
        fetched.meta.extra["user_id"] = body.user_id

    from ..store import sqlite_store
    from ..store.ingest_pipeline import ingest as pipeline_ingest

    _ensure_qdrant_collections()
    result = pipeline_ingest(fetched, force=body.force)
    resolved_paper_id = result.get("merged_into") or fetched.meta.paper_id
    n_chunks = result.get("chunks")
    if n_chunks is None:
        n_chunks = len(sqlite_store.list_chunks_for_papers([resolved_paper_id]))

    status = result.get("status", "done")
    if status == "skipped" and result.get("reason") == "done":
        status = "already_exists"
    elif status == "done":
        status = "ingested"

    return {
        **result,
        "paper_id": resolved_paper_id,
        "title": fetched.meta.title,
        "n_chunks": int(n_chunks or 0),
        "status": status,
    }


def _ensure_qdrant_collections() -> None:
    """Create Qdrant collections expected by the ingest pipeline if missing."""
    from qdrant_client.http import models as qm

    from ..store import qdrant_store

    c = cfg.load()
    client = qdrant_store.get_client()
    existing = {col.name for col in client.get_collections().collections}
    distance = qm.Distance.COSINE if c.qdrant.distance.lower() == "cosine" else qm.Distance.DOT
    vectors_config = qm.VectorParams(size=c.embedding.dim, distance=distance)

    for name in (c.qdrant.collection_chunks, c.qdrant.collection_wiki):
        if name not in existing:
            client.create_collection(collection_name=name, vectors_config=vectors_config)
