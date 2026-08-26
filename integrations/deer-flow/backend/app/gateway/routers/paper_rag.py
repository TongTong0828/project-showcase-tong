"""paper_rag HTTP router for DeerFlow.

This router exposes the sibling ``paper_rag`` package through DeerFlow's
gateway. Heavy imports stay lazy so the gateway can boot even when paper_rag
or its vector-store dependencies are not installed in the current runtime.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import logging
import os
import sqlite3
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/paper_rag", tags=["paper_rag"])


def _ensure_paper_rag_importable() -> None:
    """Add a local/sibling paper_rag checkout to ``sys.path`` when needed."""
    try:
        import paper_rag  # noqa: F401

        return
    except ImportError:
        pass

    candidates: list[Path] = []
    home = os.environ.get("PAPER_RAG_HOME")
    if home:
        h = Path(home).expanduser().resolve()
        candidates.extend([h / "src", h])

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "src")
        for dirname in ("paper-rag-agent", "paper_rag"):
            candidates.append(parent / dirname / "src")

    for candidate in candidates:
        if (candidate / "paper_rag").is_dir():
            sys.path.insert(0, str(candidate))
            return

    logger.warning("paper_rag package not found; paper_rag endpoints will return 503")


def get_current_user_id(request: Request) -> str:
    """Resolve DeerFlow's authenticated user id for paper_rag ownership."""
    user = getattr(request.state, "user", None)
    user_id = getattr(user, "id", None) or getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user_id)


def _touch_paper_access(user_id: str, chunks: list[dict] | None) -> None:
    """Best-effort stale-paper access tracking."""
    if not user_id or not chunks:
        return
    try:
        from paper_rag.proactive import paper_access
    except Exception:
        return

    paper_ids: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        pid = chunk.get("paper_id") if isinstance(chunk, dict) else None
        if pid and pid not in seen:
            seen.add(str(pid))
            paper_ids.append(str(pid))
    if not paper_ids:
        return
    try:
        paper_access.touch_many(user_id, paper_ids)
    except Exception as exc:
        logger.debug("paper_rag paper_access touch failed: %s", exc)


class QARequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    paper_ids: list[str] | None = None
    conversation_id: str | None = None
    resolved_question: str | None = None


class QASyncResponse(BaseModel):
    answer: str
    citations: list[str]
    abstain: dict[str, Any]
    trace_id: str
    n_chunks: int
    trace: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    arxiv_id: str | None = None
    pdf_url: str | None = None
    title_hint: str | None = None
    force: bool = False


class IngestResponse(BaseModel):
    paper_id: str
    title: str | None = None
    n_chunks: int
    status: str
    reason: str | None = None
    merged_into: str | None = None
    wiki: dict[str, Any] | None = None


class PaperRow(BaseModel):
    paper_id: str
    title: str | None = None
    arxiv_id: str | None = None
    n_chunks: int
    ingested_at: str | None = None


class KnowledgeBuildStage(BaseModel):
    name: str
    status: str
    error: str | None = None
    finished_at: str | None = None


class KnowledgeBuildStatus(BaseModel):
    paper_id: str
    title: str | None = None
    arxiv_id: str | None = None
    status: str
    error: str | None = None
    n_chunks: int
    ingested_at: str | None = None
    stages: list[KnowledgeBuildStage]
    wiki_status: str
    wiki_consumed: bool = False
    wiki_review_needed: bool = False
    qdrant_status: str
    warnings: list[str] = Field(default_factory=list)


class WikiResponse(BaseModel):
    paper_id: str
    summary: str
    last_updated: str | None = None
    word_count: int


class WikiGenerateResponse(BaseModel):
    paper_id: str
    status: str
    report: dict[str, Any]
    wiki: WikiResponse | None = None


class DeliverRequest(BaseModel):
    format: str = Field(..., description="markdown_survey | pptx | docx | latex_bib | pdf")
    paper_ids: list[str] = Field(..., min_length=1)
    title: str | None = Field(default=None, max_length=200)
    options: dict[str, Any] | None = None


class DeliverResponse(BaseModel):
    format: str
    filename: str
    content_base64: str
    content_type: str
    size_bytes: int
    metadata: dict[str, Any]


class FeedbackRequest(BaseModel):
    event_type: str
    trace_id: str | None = None
    conversation_id: str | None = None
    payload: dict[str, Any] | None = None


class FeedbackResponse(BaseModel):
    id: int
    status: str
    user_id: str


class SubscriptionRequest(BaseModel):
    kind: str = "keyword"
    value: str = Field(..., min_length=1, max_length=120)
    strength: str = "normal"


class SubscriptionToggle(BaseModel):
    enabled: bool


class DiscoveryRunRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    sources: list[str] | None = None
    max_candidates: int = Field(10, ge=1, le=20)
    search_limit: int = Field(25, ge=1, le=100)


class DiscoveryCandidateIngestRequest(BaseModel):
    force: bool = False


class PaperRagRuntimeStatus(BaseModel):
    importable: bool
    embedding_available: bool
    llm_configured: bool
    chat_model: str | None = None
    openai_base_url_configured: bool
    api_key_configured: bool
    evidence_only: bool
    sqlite_available: bool
    sqlite_papers: int | None = None
    qdrant_available: bool
    qdrant_collection: str | None = None
    qdrant_points: int | None = None
    wiki_enabled: bool = False
    wiki_available: bool = False
    wiki_status: str = "unavailable"
    wiki_reason: str | None = None
    warnings: list[str]


_SENTINEL_DONE = object()


def _safe_next(gen):
    try:
        return next(gen)
    except StopIteration:
        return _SENTINEL_DONE


def _load_paper_rag_config():
    from paper_rag import config as cfg

    return cfg.load()


def _missing_llm_config(c: Any) -> list[str]:
    missing = []
    if not getattr(c.llm, "base_url", None):
        missing.append("OPENAI_BASE_URL")
    if not getattr(c.llm, "api_key", None):
        missing.append("OPENAI_API_KEY")
    if not getattr(c.llm, "chat_model", None):
        missing.append("CHAT_MODEL")
    return missing


def _wiki_runtime_state() -> dict[str, Any]:
    """Product-facing wiki activation state.

    `wiki.enabled` is treated as an ops kill switch. Existing wiki entries can
    still be shown, but empty per-paper wiki builds should explain when new
    wiki generation is disabled or unavailable.
    """
    try:
        c = _load_paper_rag_config()
    except Exception as exc:
        return {
            "wiki_enabled": False,
            "wiki_available": False,
            "wiki_status": "unavailable",
            "wiki_reason": f"paper_rag config unavailable: {type(exc).__name__}: {exc}",
        }

    if not bool(getattr(c.wiki, "enabled", False)):
        return {
            "wiki_enabled": False,
            "wiki_available": False,
            "wiki_status": "disabled",
            "wiki_reason": "wiki disabled by configuration",
        }

    missing = _missing_llm_config(c)
    if missing:
        return {
            "wiki_enabled": True,
            "wiki_available": False,
            "wiki_status": "unavailable",
            "wiki_reason": f"LLM config missing: {', '.join(missing)}",
        }

    return {
        "wiki_enabled": True,
        "wiki_available": True,
        "wiki_status": "enabled",
        "wiki_reason": None,
    }


@router.get("/status", response_model=PaperRagRuntimeStatus)
async def runtime_status(
    user_id: str = Depends(get_current_user_id),
) -> PaperRagRuntimeStatus:
    """Report paper_rag runtime readiness without exposing secrets."""
    _ = user_id
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _build_runtime_status)
    return PaperRagRuntimeStatus(**data)


def _build_runtime_status() -> dict[str, Any]:
    warnings: list[str] = []
    _ensure_paper_rag_importable()
    try:
        c = _load_paper_rag_config()
    except Exception as exc:
        return {
            "importable": False,
            "embedding_available": importlib.util.find_spec("FlagEmbedding") is not None,
            "llm_configured": False,
            "chat_model": None,
            "openai_base_url_configured": False,
            "api_key_configured": False,
            "evidence_only": True,
            "sqlite_available": False,
            "sqlite_papers": None,
            "qdrant_available": False,
            "qdrant_collection": None,
            "qdrant_points": None,
            "wiki_enabled": False,
            "wiki_available": False,
            "wiki_status": "unavailable",
            "wiki_reason": f"paper_rag unavailable: {type(exc).__name__}: {exc}",
            "warnings": [f"paper_rag unavailable: {type(exc).__name__}: {exc}"],
        }

    embedding_available = importlib.util.find_spec("FlagEmbedding") is not None
    if not embedding_available:
        warnings.append("FlagEmbedding is not installed; install paper-rag[embed] for dense retrieval.")

    llm_missing = _missing_llm_config(c)
    llm_configured = not llm_missing
    if not llm_configured:
        warnings.append(f"LLM config missing: {', '.join(llm_missing)}; QA will use evidence-only fallback.")

    wiki_state = _wiki_runtime_state()
    if wiki_state["wiki_reason"] and not wiki_state["wiki_available"]:
        warnings.append(f"Wiki build unavailable: {wiki_state['wiki_reason']}.")

    sqlite_papers = _count_sqlite_papers(c.paths.sqlite_path)
    sqlite_available = sqlite_papers is not None
    if not sqlite_available:
        warnings.append(f"SQLite store unavailable at {c.paths.sqlite_path}.")

    qdrant_collection = c.qdrant.collection_chunks
    qdrant_points, qdrant_warning = _count_qdrant_points(qdrant_collection)
    qdrant_available = qdrant_points is not None
    if qdrant_warning:
        warnings.append(qdrant_warning)

    return {
        "importable": True,
        "embedding_available": embedding_available,
        "llm_configured": llm_configured,
        "chat_model": c.llm.chat_model,
        "openai_base_url_configured": bool(c.llm.base_url),
        "api_key_configured": bool(c.llm.api_key),
        "evidence_only": not llm_configured,
        "sqlite_available": sqlite_available,
        "sqlite_papers": sqlite_papers,
        "qdrant_available": qdrant_available,
        "qdrant_collection": qdrant_collection,
        "qdrant_points": qdrant_points,
        **wiki_state,
        "warnings": warnings,
    }


def _count_sqlite_papers(sqlite_path: str) -> int | None:
    path = Path(sqlite_path)
    if not path.exists():
        return None
    con = sqlite3.connect(str(path))
    try:
        table_names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        papers_table = "paper" if "paper" in table_names else "papers"
        if papers_table not in table_names:
            return 0
        return int(con.execute(f"SELECT COUNT(*) FROM {papers_table}").fetchone()[0] or 0)
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _count_qdrant_points(collection: str) -> tuple[int | None, str | None]:
    try:
        from paper_rag.store import qdrant_store

        client = qdrant_store.get_client()
        count = client.count(collection_name=collection, exact=False)
        return int(getattr(count, "count", count) or 0), None
    except Exception as exc:
        return None, f"Qdrant collection {collection} unavailable: {type(exc).__name__}: {exc}"


@router.post("/qa")
async def qa_stream(
    body: QARequest,
    user_id: str = Depends(get_current_user_id),
) -> EventSourceResponse:
    """Streaming paper Q&A."""
    _ensure_paper_rag_importable()
    try:
        from paper_rag.rag.qa_stream import stream_answer
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag package unavailable: {exc}") from exc

    async def _gen() -> AsyncGenerator[dict[str, str], None]:
        loop = asyncio.get_running_loop()
        gen = stream_answer(
            body.question,
            paper_ids=body.paper_ids,
            conversation_id=body.conversation_id,
            user_id=user_id,
            resolved_question=body.resolved_question,
        )
        touched_paper_ids: list[str] = []
        try:
            while True:
                evt = await loop.run_in_executor(None, _safe_next, gen)
                if evt is _SENTINEL_DONE:
                    break
                if evt.get("event") == "done":
                    pids = evt.get("data", {}).get("paper_ids") or []
                    if isinstance(pids, list):
                        touched_paper_ids = [str(pid) for pid in pids if pid]
                yield {"event": evt["event"], "data": json.dumps(evt["data"], ensure_ascii=False)}
        except Exception as exc:
            logger.exception("paper_rag qa stream failed")
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}
        finally:
            if touched_paper_ids:
                chunks_view = [{"paper_id": pid} for pid in touched_paper_ids]
                await loop.run_in_executor(None, _touch_paper_access, user_id, chunks_view)

    return EventSourceResponse(_gen())


@router.post("/qa/sync", response_model=QASyncResponse)
async def qa_sync(
    body: QARequest,
    user_id: str = Depends(get_current_user_id),
) -> QASyncResponse:
    """Non-streaming paper Q&A."""
    _ensure_paper_rag_importable()
    try:
        from paper_rag.rag.qa_agentic import answer
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag package unavailable: {exc}") from exc

    loop = asyncio.get_running_loop()
    try:
        out = await loop.run_in_executor(
            None,
            lambda: answer(
                body.question,
                paper_ids=body.paper_ids,
                conversation_id=body.conversation_id,
                user_id=user_id,
                resolved_question=body.resolved_question,
            ),
        )
    except Exception as exc:
        logger.exception("paper_rag qa_sync failed")
        raise HTTPException(503, f"paper_rag QA unavailable: {exc}") from exc
    chunks_used = out.get("chunks", []) or []
    if chunks_used:
        await loop.run_in_executor(None, _touch_paper_access, user_id, chunks_used)
    trace = out.get("trace", {}) or {}
    return QASyncResponse(
        answer=out.get("answer", ""),
        citations=out.get("citations", []),
        abstain=trace.get("abstain", {}),
        trace_id=trace.get("trace_id", ""),
        n_chunks=len(chunks_used),
        trace=trace,
        memory=trace.get("memory"),
    )


@router.get("/papers", response_model=list[PaperRow])
async def list_papers(
    user_id: str = Depends(get_current_user_id),
    limit: int = 100,
) -> list[PaperRow]:
    """List papers visible to the user."""
    _ensure_paper_rag_importable()
    try:
        from paper_rag.store import sqlite_store
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag unavailable: {exc}") from exc

    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, _list_papers_for_user, sqlite_store, user_id, limit)
    return [PaperRow(**row) for row in rows]


def _list_papers_for_user(store, user_id: str, limit: int) -> list[dict[str, Any]]:
    sqlite_path = getattr(store, "SQLITE_PATH", None) or _resolve_sqlite_path()
    if not Path(sqlite_path).exists():
        return []

    con = sqlite3.connect(str(sqlite_path))
    con.row_factory = sqlite3.Row
    try:
        table_names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        papers_table = "paper" if "paper" in table_names else "papers"
        chunks_table = "chunk" if "chunk" in table_names else "chunks"
        if papers_table not in table_names:
            return []

        cols = {row[1] for row in con.execute(f"PRAGMA table_info({papers_table})")}
        if "user_id" in cols:
            cur = con.execute(
                f"SELECT paper_id, title, arxiv_id, created_at FROM {papers_table} "
                "WHERE user_id = ? OR user_id = 'system' OR user_id IS NULL "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        else:
            cur = con.execute(
                f"SELECT paper_id, title, arxiv_id, created_at FROM {papers_table} "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

        rows: list[dict[str, Any]] = []
        for row in cur:
            paper_id = row["paper_id"]
            n_chunks = 0
            if chunks_table in table_names:
                n_chunks = con.execute(
                    f"SELECT COUNT(*) AS n FROM {chunks_table} WHERE paper_id = ?",
                    (paper_id,),
                ).fetchone()["n"]
            rows.append(
                {
                    "paper_id": paper_id,
                    "title": row["title"],
                    "arxiv_id": row["arxiv_id"],
                    "n_chunks": int(n_chunks or 0),
                    "ingested_at": str(row["created_at"]) if row["created_at"] is not None else None,
                }
            )
        return rows
    finally:
        con.close()


def _resolve_sqlite_path() -> str:
    from paper_rag import config as cfg

    return cfg.load().paths.sqlite_path


@router.get("/knowledge/builds", response_model=list[KnowledgeBuildStatus])
async def list_knowledge_builds(
    user_id: str = Depends(get_current_user_id),
    limit: int = 100,
) -> list[KnowledgeBuildStatus]:
    """Return product-facing paper knowledge-base build status."""
    _ensure_paper_rag_importable()
    try:
        c = _load_paper_rag_config()
    except Exception as exc:
        raise HTTPException(503, f"paper_rag unavailable: {exc}") from exc

    qdrant_points, qdrant_warning = _count_qdrant_points(c.qdrant.collection_chunks)
    qdrant_status = "online" if qdrant_points is not None else "offline"
    wiki_runtime = _wiki_runtime_state()
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(
        None,
        _list_knowledge_builds_for_user,
        user_id,
        limit,
        qdrant_status,
        qdrant_warning,
        wiki_runtime,
    )
    return [KnowledgeBuildStatus(**row) for row in rows]


def _list_knowledge_builds_for_user(
    user_id: str,
    limit: int,
    qdrant_status: str,
    qdrant_warning: str | None,
    wiki_runtime: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    wiki_runtime = wiki_runtime or _wiki_runtime_state()
    sqlite_path = _resolve_sqlite_path()
    if not Path(sqlite_path).exists():
        return []

    con = sqlite3.connect(str(sqlite_path))
    con.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        papers_table = "paper" if "paper" in tables else "papers"
        chunks_table = "chunk" if "chunk" in tables else "chunks"
        if papers_table not in tables:
            return []

        paper_cols = {row[1] for row in con.execute(f"PRAGMA table_info({papers_table})")}
        select_cols = [
            "paper_id",
            "title",
            "arxiv_id",
            "created_at",
            "status" if "status" in paper_cols else "NULL AS status",
            "error" if "error" in paper_cols else "NULL AS error",
        ]
        if "user_id" in paper_cols:
            cur = con.execute(
                f"SELECT {', '.join(select_cols)} FROM {papers_table} "
                "WHERE user_id = ? OR user_id = 'system' OR user_id IS NULL "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        else:
            cur = con.execute(
                f"SELECT {', '.join(select_cols)} FROM {papers_table} "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

        out: list[dict[str, Any]] = []
        for row in cur:
            paper_id = row["paper_id"]
            n_chunks = _count_chunks_for_paper(con, tables, chunks_table, paper_id)
            ingest_steps = _latest_ingest_steps(con, tables, paper_id)
            wiki_status = _wiki_status_for_paper(con, tables, paper_id)
            if wiki_status == "empty" and not bool(wiki_runtime.get("wiki_available")):
                wiki_status = str(wiki_runtime.get("wiki_status") or "unavailable")
            wiki_consumed = _wiki_consumed_for_paper(con, tables, paper_id)
            wiki_review_needed = _wiki_review_needed_for_paper(con, tables, paper_id)
            stages = _knowledge_stages(row, ingest_steps, wiki_status)
            warnings = []
            if qdrant_warning:
                warnings.append(qdrant_warning)
            if wiki_status == "empty":
                warnings.append("Wiki entry has not been generated for this paper.")
            elif wiki_status == "disabled":
                warnings.append("Wiki auto-build is disabled by configuration.")
            elif wiki_status == "unavailable":
                reason = wiki_runtime.get("wiki_reason") or "wiki runtime is unavailable"
                warnings.append(f"Wiki build unavailable: {reason}.")
            if wiki_review_needed:
                warnings.append("Wiki entry needs review based on QA or feedback signals.")
            out.append(
                {
                    "paper_id": paper_id,
                    "title": row["title"],
                    "arxiv_id": row["arxiv_id"],
                    "status": row["status"] or "unknown",
                    "error": row["error"],
                    "n_chunks": n_chunks,
                    "ingested_at": str(row["created_at"]) if row["created_at"] is not None else None,
                    "stages": stages,
                    "wiki_status": wiki_status,
                    "wiki_consumed": wiki_consumed,
                    "wiki_review_needed": wiki_review_needed,
                    "qdrant_status": qdrant_status,
                    "warnings": warnings,
                }
            )
        return out
    finally:
        con.close()


def _count_chunks_for_paper(con: sqlite3.Connection, tables: set[str], chunks_table: str, paper_id: str) -> int:
    if chunks_table not in tables:
        return 0
    row = con.execute(
        f"SELECT COUNT(*) AS n FROM {chunks_table} WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    return int(row["n"] or 0)


def _latest_ingest_steps(con: sqlite3.Connection, tables: set[str], paper_id: str) -> dict[str, dict[str, Any]]:
    if "ingest_runs" not in tables:
        return {}
    rows = list(
        con.execute(
            """
            SELECT step, status, error, finished_at
            FROM ingest_runs
            WHERE paper_id = ?
            ORDER BY id ASC
            """,
            (paper_id,),
        )
    )
    steps: dict[str, dict[str, Any]] = {}
    for row in rows:
        steps[row["step"]] = {
            "status": row["status"] or "pending",
            "error": row["error"],
            "finished_at": str(row["finished_at"]) if row["finished_at"] else None,
        }
    return steps


def _wiki_status_for_paper(con: sqlite3.Connection, tables: set[str], paper_id: str) -> str:
    if "wiki_entries" not in tables:
        return "empty"
    try:
        rows = list(con.execute("SELECT key_papers_json FROM wiki_entries"))
    except sqlite3.Error:
        return "empty"
    for row in rows:
        try:
            key_papers = json.loads(row["key_papers_json"] or "[]")
        except Exception:
            key_papers = []
        if paper_id in key_papers:
            return "ready"
    return "empty"


def _wiki_consumed_for_paper(con: sqlite3.Connection, tables: set[str], paper_id: str) -> bool:
    if "wiki_consumption_events" not in tables:
        return False
    try:
        row = con.execute(
            "SELECT 1 FROM wiki_consumption_events WHERE paper_id = ? LIMIT 1",
            (paper_id,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _wiki_review_needed_for_paper(con: sqlite3.Connection, tables: set[str], paper_id: str) -> bool:
    if "wiki_review_queue" not in tables:
        return False
    try:
        row = con.execute(
            "SELECT 1 FROM wiki_review_queue WHERE paper_id = ? AND status = 'pending' LIMIT 1",
            (paper_id,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _knowledge_stages(row: sqlite3.Row, ingest_steps: dict[str, dict[str, Any]], wiki_status: str) -> list[dict[str, Any]]:
    paper_status = row["status"] or "unknown"
    paper_error = row["error"]
    stages: list[dict[str, Any]] = [
        {
            "name": "fetch",
            "status": "error" if paper_status == "failed" and paper_error else "ok",
            "error": paper_error if paper_status == "failed" and paper_error else None,
            "finished_at": str(row["created_at"]) if row["created_at"] else None,
        }
    ]
    for name in ("parse", "chunk", "embed", "index"):
        step = ingest_steps.get(name)
        if step:
            stages.append({"name": name, **step})
        elif paper_status == "done":
            stages.append({"name": name, "status": "ok", "error": None, "finished_at": None})
        elif paper_status == "failed":
            stages.append({"name": name, "status": "pending", "error": None, "finished_at": None})
        else:
            stages.append({"name": name, "status": "pending", "error": None, "finished_at": None})
    stages.append({"name": "wiki", "status": wiki_status, "error": None, "finished_at": None})
    return stages


def _attach_user_id_to_fetch_meta(fetched: Any, user_id: str) -> None:
    meta = getattr(fetched, "meta", None)
    if meta is None:
        return
    try:
        setattr(meta, "user_id", user_id)
        return
    except (AttributeError, ValueError):
        pass

    extra = getattr(meta, "extra", None)
    if isinstance(extra, dict):
        extra["user_id"] = user_id


@router.post("/discovery/run")
async def run_discovery(
    body: DiscoveryRunRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Run a bounded paper discovery loop for a research topic."""
    _ensure_paper_rag_importable()
    try:
        from paper_rag.discovery import runner
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag.discovery unavailable: {exc}") from exc

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: runner.run_discovery(
                body.topic,
                user_id=user_id,
                source_names=body.sources,
                max_candidates=body.max_candidates,
                search_limit=body.search_limit,
            ),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("paper_rag discovery failed")
        raise HTTPException(503, f"paper_rag discovery unavailable: {exc}") from exc


@router.get("/discovery/runs")
async def list_discovery_runs(
    user_id: str = Depends(get_current_user_id),
    limit: int = 20,
) -> list[dict[str, Any]]:
    _ensure_paper_rag_importable()
    try:
        from paper_rag.discovery import store
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag.discovery unavailable: {exc}") from exc
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: store.list_runs(user_id, limit=limit))


@router.get("/discovery/runs/{run_id}")
async def get_discovery_run(
    run_id: int,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    try:
        from paper_rag.discovery import store
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag.discovery unavailable: {exc}") from exc
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: store.get_run(run_id, user_id=user_id))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/discovery/candidates/{candidate_id}/ingest")
async def ingest_discovery_candidate(
    candidate_id: int,
    body: DiscoveryCandidateIngestRequest | None = None,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Manually ingest a selected discovery candidate."""
    _ensure_paper_rag_importable()
    try:
        from paper_rag.discovery import runner
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag.discovery unavailable: {exc}") from exc

    force = body.force if body else False
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: runner.ingest_candidate(candidate_id, user_id=user_id, force=force),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("paper_rag discovery candidate ingest failed")
        raise HTTPException(503, f"paper_rag discovery ingest unavailable: {exc}") from exc


@router.post("/papers/ingest", response_model=IngestResponse)
async def ingest_paper(
    body: IngestRequest,
    user_id: str = Depends(get_current_user_id),
) -> IngestResponse:
    """Ingest a paper by arXiv id or direct PDF URL."""
    if not body.arxiv_id and not body.pdf_url:
        raise HTTPException(400, "Provide either arxiv_id or pdf_url")
    _ensure_paper_rag_importable()

    try:
        from paper_rag.ingest.arxiv_source import ArxivSource
        from paper_rag.ingest.url_source import UrlSource
        from paper_rag.store.ingest_pipeline import ingest
        from paper_rag.utils.paths import ensure_dirs
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag ingest unavailable: {exc}") from exc

    def _run() -> dict[str, Any]:
        ensure_dirs()
        if body.arxiv_id:
            fetched = ArxivSource().fetch(body.arxiv_id)
        else:
            fetched = UrlSource(title=body.title_hint).fetch(body.pdf_url or "")
        _attach_user_id_to_fetch_meta(fetched, user_id)
        return ingest(fetched, force=body.force)

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _run)
    except Exception as exc:
        logger.exception("paper_rag ingest failed")
        raise HTTPException(503, f"paper_rag ingest unavailable: {exc}") from exc
    return IngestResponse(
        paper_id=result.get("paper_id", ""),
        title=result.get("title"),
        n_chunks=int(result.get("chunks", result.get("n_chunks", 0)) or 0),
        status=result.get("status", "ingested"),
        reason=result.get("reason"),
        merged_into=result.get("merged_into"),
        wiki=result.get("wiki") if isinstance(result.get("wiki"), dict) else None,
    )


@router.get("/wiki/{paper_id}", response_model=WikiResponse)
async def get_wiki(
    paper_id: str,
    user_id: str = Depends(get_current_user_id),
) -> WikiResponse:
    """Return the generated wiki entry for a paper."""
    _ = user_id
    _ensure_paper_rag_importable()
    try:
        from paper_rag.wiki import store as wiki_store
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag unavailable: {exc}") from exc

    loop = asyncio.get_running_loop()
    entry = await loop.run_in_executor(None, _lookup_wiki_for_paper, wiki_store, paper_id)
    if not entry:
        raise HTTPException(404, f"No wiki entry for paper_id={paper_id}")
    summary = entry.get("summary", "")
    last_updated = entry.get("last_updated")
    return WikiResponse(
        paper_id=paper_id,
        summary=summary,
        last_updated=str(last_updated) if last_updated else None,
        word_count=len(summary.split()),
    )


@router.post("/wiki/{paper_id}/generate", response_model=WikiGenerateResponse)
async def generate_wiki(
    paper_id: str,
    user_id: str = Depends(get_current_user_id),
) -> WikiGenerateResponse:
    """Generate or refresh concept-wiki entries for a paper on demand."""
    _ = user_id
    _ensure_paper_rag_importable()
    try:
        from paper_rag.wiki import store as wiki_store
        from paper_rag.wiki import triggers
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag wiki unavailable: {exc}") from exc

    loop = asyncio.get_running_loop()
    report, entry = await loop.run_in_executor(
        None,
        lambda: _generate_wiki_for_paper(triggers, wiki_store, paper_id),
    )
    if "error" in report:
        message = str(report["error"])
        if "paper not found" in message:
            raise HTTPException(404, message)
        raise HTTPException(503, message)

    wiki = None
    if entry:
        summary = entry.get("summary", "")
        last_updated = entry.get("last_updated")
        wiki = WikiResponse(
            paper_id=paper_id,
            summary=summary,
            last_updated=str(last_updated) if last_updated else None,
            word_count=len(summary.split()),
        )
    return WikiGenerateResponse(
        paper_id=paper_id,
        status="generated" if wiki else "empty",
        report=report,
        wiki=wiki,
    )


def _generate_wiki_for_paper(triggers, wiki_store, paper_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    report = triggers.on_paper_indexed(paper_id, force=True)
    entry = _lookup_wiki_for_paper(wiki_store, paper_id)
    return report, entry


def _lookup_wiki_for_paper(wiki_store, paper_id: str) -> dict[str, Any] | None:
    """Adapt current concept-wiki storage to the paper-level HTTP endpoint."""
    direct_get = getattr(wiki_store, "get", None)
    if callable(direct_get):
        direct = direct_get(paper_id)
        if direct:
            return _wiki_entry_to_response(direct)

    get_entry = getattr(wiki_store, "get_entry", None)
    if callable(get_entry):
        direct = get_entry(paper_id)
        if direct:
            return _wiki_entry_to_response(direct)

    list_all = getattr(wiki_store, "list_all", None)
    if not callable(list_all):
        return None

    try:
        entries = list_all()
    except Exception as exc:
        logger.debug("paper_rag wiki lookup skipped: %s", exc)
        return None

    matches = []
    for entry in entries:
        key_papers = getattr(entry, "key_papers", None)
        if isinstance(entry, dict):
            key_papers = entry.get("key_papers")
        if paper_id in (key_papers or []):
            matches.append(entry)

    if not matches:
        return None

    blocks = []
    updated_at = None
    for entry in matches:
        name = entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", "")
        definition = (
            entry.get("definition") if isinstance(entry, dict) else getattr(entry, "definition", "")
        )
        blocks.append(f"## {name}\n{definition}".strip())
        candidate_updated = (
            entry.get("updated_at") if isinstance(entry, dict) else getattr(entry, "updated_at", None)
        )
        if candidate_updated:
            updated_at = candidate_updated
    return {"summary": "\n\n".join(blocks), "last_updated": updated_at}


def _wiki_entry_to_response(entry) -> dict[str, Any]:
    if isinstance(entry, dict):
        summary = entry.get("summary") or entry.get("definition") or ""
        return {"summary": summary, "last_updated": entry.get("last_updated") or entry.get("updated_at")}
    summary = getattr(entry, "summary", None) or getattr(entry, "definition", "")
    return {"summary": summary, "last_updated": getattr(entry, "last_updated", None) or getattr(entry, "updated_at", None)}


@router.post("/deliver", response_model=DeliverResponse)
async def deliver(
    body: DeliverRequest,
    user_id: str = Depends(get_current_user_id),
) -> DeliverResponse:
    """Generate a paper deliverable artifact."""
    _ensure_paper_rag_importable()
    try:
        from paper_rag.deliver.dispatch import DeliverError, dispatch
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag.deliver unavailable: {exc}") from exc

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: dispatch(
                body.format,
                body.paper_ids,
                title=body.title,
                options=body.options,
                user_id=user_id,
            ),
        )
    except DeliverError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc

    return DeliverResponse(
        format=result.format,
        filename=result.filename,
        content_base64=base64.b64encode(result.content_bytes).decode("ascii"),
        content_type=result.content_type,
        size_bytes=len(result.content_bytes),
        metadata=result.metadata,
    )


@router.post("/feedback", response_model=FeedbackResponse)
async def post_feedback(
    body: FeedbackRequest,
    user_id: str = Depends(get_current_user_id),
) -> FeedbackResponse:
    _ensure_paper_rag_importable()
    try:
        from paper_rag.feedback import record_event
    except ImportError as exc:
        raise HTTPException(503, f"paper_rag.feedback unavailable: {exc}") from exc

    loop = asyncio.get_running_loop()
    try:
        event_id = await loop.run_in_executor(
            None,
            lambda: record_event(
                user_id=user_id,
                event_type=body.event_type,
                payload=body.payload or {},
                trace_id=body.trace_id,
                conversation_id=body.conversation_id,
            ),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(429, str(exc)) from exc
    return FeedbackResponse(id=event_id, status="recorded", user_id=user_id)


@router.get("/feedback/recent")
async def list_recent_feedback(
    user_id: str = Depends(get_current_user_id),
    limit: int = 20,
) -> list[dict[str, Any]]:
    _ensure_paper_rag_importable()
    from paper_rag.feedback import recent_events

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, recent_events, user_id, limit)


@router.get("/feedback/stats")
async def feedback_stats(
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.feedback import user_stats

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, user_stats, user_id)


@router.get("/subscriptions")
async def list_subscriptions(
    user_id: str = Depends(get_current_user_id),
) -> list[dict[str, Any]]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import subscriptions

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: subscriptions.list_for_user(user_id, only_enabled=False),
    )


@router.post("/subscriptions")
async def add_subscription(
    body: SubscriptionRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import subscriptions

    loop = asyncio.get_running_loop()
    try:
        sub_id = await loop.run_in_executor(
            None,
            lambda: subscriptions.add(user_id, body.kind, body.value, strength=body.strength),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": sub_id, "status": "subscribed", "kind": body.kind, "value": body.value, "strength": body.strength}


@router.delete("/subscriptions/{sub_id}")
async def delete_subscription(
    sub_id: int,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import subscriptions

    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, lambda: subscriptions.delete(sub_id, user_id=user_id))
    if not ok:
        raise HTTPException(404, f"subscription {sub_id} not found for user")
    return {"id": sub_id, "status": "deleted"}


@router.patch("/subscriptions/{sub_id}")
async def toggle_subscription(
    sub_id: int,
    body: SubscriptionToggle,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import subscriptions

    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(
        None,
        lambda: subscriptions.toggle(sub_id, enabled=body.enabled, user_id=user_id),
    )
    if not ok:
        raise HTTPException(404, f"subscription {sub_id} not found for user")
    return {"id": sub_id, "enabled": body.enabled}


@router.get("/inbox")
async def list_inbox(
    user_id: str = Depends(get_current_user_id),
    unread_only: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import inbox

    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(
        None,
        lambda: inbox.list_for_user(user_id, unread_only=unread_only, limit=limit),
    )
    unread = await loop.run_in_executor(None, inbox.unread_count, user_id)
    return {"items": items, "unread_count": unread}


@router.get("/inbox/stream")
async def stream_inbox(
    user_id: str = Depends(get_current_user_id),
    poll_seconds: float = 5.0,
) -> EventSourceResponse:
    """Long-poll SSE stream for new unread inbox items."""
    _ensure_paper_rag_importable()
    from paper_rag.proactive import inbox

    poll_seconds = max(1.0, min(float(poll_seconds), 30.0))

    async def _gen() -> AsyncGenerator[dict[str, str], None]:
        loop = asyncio.get_running_loop()
        seen_ids: set[int] = set()
        try:
            existing = await loop.run_in_executor(
                None,
                lambda: inbox.list_for_user(user_id, unread_only=True, limit=200),
            )
            seen_ids = {int(item["id"]) for item in existing if item.get("id")}
        except Exception:
            pass

        while True:
            try:
                items = await loop.run_in_executor(
                    None,
                    lambda: inbox.list_for_user(user_id, unread_only=True, limit=50),
                )
            except Exception as exc:
                logger.warning("paper_rag inbox stream poll failed: %s", exc)
                items = []
            for item in items:
                item_id = item.get("id")
                if item_id is None or int(item_id) in seen_ids:
                    continue
                seen_ids.add(int(item_id))
                yield {
                    "event": "inbox",
                    "data": json.dumps(
                        {
                            "id": item_id,
                            "kind": item.get("kind"),
                            "title": item.get("title"),
                            "created_at": item.get("created_at"),
                        },
                        ensure_ascii=False,
                    ),
                }
            yield {"event": "ping", "data": json.dumps({"ts": loop.time()})}
            await asyncio.sleep(poll_seconds)

    return EventSourceResponse(_gen())


@router.post("/inbox/{item_id}/read")
async def mark_inbox_read(
    item_id: int,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import inbox

    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, lambda: inbox.mark_read(item_id, user_id=user_id))
    return {"id": item_id, "marked_read": ok}


@router.post("/inbox/{item_id}/dismiss")
async def dismiss_inbox(
    item_id: int,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import inbox

    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, lambda: inbox.dismiss(item_id, user_id=user_id))
    return {"id": item_id, "dismissed": ok}


@router.post("/proactive/digest/run")
async def run_digest_now(
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import digest

    loop = asyncio.get_running_loop()
    item_id = await loop.run_in_executor(None, lambda: digest.daily_digest_for_user(user_id))
    return {"user_id": user_id, "inbox_item_id": item_id, "wrote": bool(item_id)}


@router.post("/proactive/stale/run")
async def run_stale_now(
    user_id: str = Depends(get_current_user_id),
    days: int = 30,
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import stale

    loop = asyncio.get_running_loop()
    n_cards = await loop.run_in_executor(None, lambda: stale.stale_scan_for_user(user_id, older_than_days=days))
    return {"user_id": user_id, "n_cards": n_cards}
