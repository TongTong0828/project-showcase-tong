"""paper_rag HTTP router (M8 service-ization, ADR-0015).

Exposes the standalone `paper_rag` package as first-class HTTP endpoints on
the DeerFlow gateway. Re-uses the same underlying functions (`qa_agentic`,
`qa_stream`, `paper_index`) that lead_agent's LangChain tools call — only
the outer adapter differs (router vs @tool).

Endpoints
---------
POST   /api/paper_rag/qa                Streaming SSE Q&A
POST   /api/paper_rag/qa/sync           Synchronous Q&A
GET    /api/paper_rag/papers            List user's papers
POST   /api/paper_rag/papers/ingest     Ingest by arxiv id / pdf url
POST   /api/paper_rag/discovery/run     Discover candidate papers for a topic
GET    /api/paper_rag/discovery/runs    List discovery runs
GET    /api/paper_rag/discovery/runs/{run_id}
POST   /api/paper_rag/discovery/candidates/{candidate_id}/ingest
GET    /api/paper_rag/status            Runtime readiness and wiki activation
GET    /api/paper_rag/knowledge/builds  Knowledge Builder status
GET    /api/paper_rag/wiki/{paper_id}   Wiki entry for a paper

Auth
----
All endpoints require a valid BetterAuth session (see middleware/auth.py).
The middleware injects ``request.state.user_id`` which routers consume via
``Depends(get_current_user_id)``.

Notes
-----
- paper_rag is a *separate* Python package not in the backend monorepo. We
  use the same path-discovery trick as the LangChain tool adapter (env
  PAPER_RAG_HOME, then walk up to find sibling paper_rag/src).
- Heavy imports (qa_agentic, qdrant) are lazy — keeps gateway start fast.
"""

from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# Lazy import of the standalone paper_rag package
# ---------------------------------------------------------------------------


def _ensure_paper_rag_importable() -> None:
    """Make the standalone paper_rag package importable.

    Resolution order:
      1. Already importable (e.g. pip install -e ..) -> done.
      2. Env var PAPER_RAG_HOME -> use that path (must contain src/paper_rag).
      3. Walk up parents from this file to find sibling paper_rag/src/paper_rag.
    """
    try:
        import paper_rag  # noqa: F401

        return
    except ImportError:
        pass

    home = os.environ.get("PAPER_RAG_HOME")
    if home:
        candidate = Path(home).expanduser().resolve() / "src"
        if not candidate.is_dir():
            # PAPER_RAG_HOME may already point at src/
            candidate = Path(home).expanduser().resolve()
    else:
        here = Path(__file__).resolve()
        candidate = None
        for parent in here.parents:
            maybe = parent / "paper_rag" / "src" / "paper_rag"
            if maybe.is_dir():
                candidate = parent / "paper_rag" / "src"
                break

    if candidate and candidate.is_dir():
        sys.path.insert(0, str(candidate))
    else:
        logger.warning(
            "paper_rag package not found on PYTHONPATH or via PAPER_RAG_HOME — "
            "router endpoints will return 503"
        )


# ---------------------------------------------------------------------------
# Auth dependency (will be backed by BetterAuth middleware in middleware/auth.py)
# ---------------------------------------------------------------------------


def get_current_user_id(request: Request) -> str:
    """Pull the authenticated user_id from request state.

    The auth middleware sets request.state.user_id after validating a
    BetterAuth session token. If missing -> 401.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _touch_paper_access(user_id: str, chunks: list[dict] | None) -> None:
    """Record paper-access timestamps for stale-card scanning (M9 / ADR-0018).

    Best-effort: any failure is logged at DEBUG and swallowed — paper_access is
    metadata, never blocking. Extracts unique paper_ids from `chunks`
    (whatever subset the QA pipeline actually used as evidence) and forwards
    them to ``proactive.paper_access.touch_many``.
    """
    if not user_id or not chunks:
        return
    try:
        from paper_rag.proactive import paper_access  # type: ignore
    except Exception:  # noqa: BLE001 — package may be unavailable in tests
        return
    paper_ids: list[str] = []
    seen: set[str] = set()
    for c in chunks:
        pid = c.get("paper_id") if isinstance(c, dict) else None
        if pid and pid not in seen:
            seen.add(pid)
            paper_ids.append(str(pid))
    if not paper_ids:
        return
    try:
        paper_access.touch_many(user_id, paper_ids)
    except Exception as e:  # noqa: BLE001 — never block QA on metadata
        logger.debug("paper_access touch_many failed (non-fatal): %s", e)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class QARequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    paper_ids: list[str] | None = Field(default=None, description="Filter to these papers; null = whole library")
    conversation_id: str | None = Field(default=None, description="Multi-turn conversation thread id")
    resolved_question: str | None = Field(default=None, description="Caller-resolved self-contained question")


class QASyncResponse(BaseModel):
    answer: str
    citations: list[str]
    abstain: dict[str, Any]
    trace_id: str
    n_chunks: int
    trace: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    arxiv_id: str | None = Field(default=None, description="e.g. 2310.11511 or 2310.11511v3")
    pdf_url: str | None = Field(default=None, description="Direct PDF URL")
    title_hint: str | None = Field(default=None, description="Title hint when only PDF URL is given")


class IngestResponse(BaseModel):
    paper_id: str
    title: str | None
    n_chunks: int
    status: str  # "ingested" | "already_exists"


class PaperRow(BaseModel):
    paper_id: str
    title: str | None
    arxiv_id: str | None
    n_chunks: int
    ingested_at: str | None


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


class WikiResponse(BaseModel):
    paper_id: str
    summary: str
    last_updated: str | None
    word_count: int


class DeliverRequest(BaseModel):
    format: str = Field(..., description="One of: markdown_survey | pptx | docx | latex_bib")
    paper_ids: list[str] = Field(..., min_length=1)
    title: str | None = Field(default=None, max_length=200)
    options: dict[str, Any] | None = Field(default=None)


class DeliverResponse(BaseModel):
    format: str
    filename: str
    content_base64: str
    content_type: str
    size_bytes: int
    metadata: dict[str, Any]


class FeedbackRequest(BaseModel):
    event_type: str = Field(..., description="One of: thumbs_up, thumbs_down, copy_answer, follow_up_question, abandon, abstain_followup_ingest, judge_score")
    trace_id: str | None = Field(default=None)
    conversation_id: str | None = Field(default=None)
    payload: dict[str, Any] | None = Field(default=None)


class FeedbackResponse(BaseModel):
    id: int
    status: str
    user_id: str


class SubscriptionRequest(BaseModel):
    kind: str = Field("keyword", description="keyword | topic_vector | arxiv_category")
    value: str = Field(..., min_length=1, max_length=120)
    strength: str = Field("normal", description="low | normal | high")


class SubscriptionToggle(BaseModel):
    enabled: bool


class DiscoveryRunRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    sources: list[str] | None = None
    max_candidates: int = Field(10, ge=1, le=20)
    search_limit: int = Field(25, ge=1, le=100)


class DiscoveryCandidateIngestRequest(BaseModel):
    force: bool = False


class InboxItemAction(BaseModel):
    item_id: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/qa")
async def qa_stream(
    body: QARequest,
    user_id: str = Depends(get_current_user_id),
) -> EventSourceResponse:
    """Streaming Q&A — yields SSE events from paper_rag.rag.qa_stream.

    Event types: intent / rewrite / retrieved / reflect / abstain /
    answer_chunk / done / error. The protocol is unchanged from
    qa_stream.stream_answer() — see ADR-0014 for abstain event.
    """
    _ensure_paper_rag_importable()
    try:
        from paper_rag.rag.qa_stream import stream_answer
    except ImportError as e:
        raise HTTPException(503, f"paper_rag package unavailable: {e}")

    async def _gen() -> AsyncGenerator[dict[str, str], None]:
        loop = asyncio.get_running_loop()
        # stream_answer is a SYNCHRONOUS generator; iterate it in a thread
        # so the gateway event loop is never blocked. Each yielded dict is
        # serialized as one SSE event.
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
                # M9 / ADR-0018: capture paper_ids on `done` for stale tracking
                if evt.get("event") == "done":
                    pids = evt.get("data", {}).get("paper_ids") or []
                    if isinstance(pids, list):
                        touched_paper_ids = [str(p) for p in pids if p]
                yield {"event": evt["event"], "data": json.dumps(evt["data"], ensure_ascii=False)}
        except Exception as e:
            logger.exception("paper_rag qa stream failed")
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
        finally:
            # Fire-and-forget paper_access.touch_many — failures stay in DEBUG
            if touched_paper_ids:
                try:
                    chunks_view = [{"paper_id": pid} for pid in touched_paper_ids]
                    await loop.run_in_executor(None, _touch_paper_access, user_id, chunks_view)
                except Exception:  # noqa: BLE001
                    pass

    return EventSourceResponse(_gen())


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

    qdrant_collection = getattr(c.qdrant, "collection_chunks", "paper_chunks")
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


@router.post("/qa/sync", response_model=QASyncResponse)
async def qa_sync(
    body: QARequest,
    user_id: str = Depends(get_current_user_id),
) -> QASyncResponse:
    """Non-streaming Q&A — convenient for curl / scripts / 3rd-party integrations."""
    _ensure_paper_rag_importable()
    try:
        from paper_rag.rag.qa_agentic import answer
    except ImportError as e:
        raise HTTPException(503, f"paper_rag package unavailable: {e}")

    loop = asyncio.get_running_loop()
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
    # M9 / ADR-0018: record paper_access for stale-card scanning. Run in the
    # same executor (off-loop) so it does not delay the response.
    chunks_used = out.get("chunks", []) or []
    if chunks_used:
        await loop.run_in_executor(None, _touch_paper_access, user_id, chunks_used)
    return QASyncResponse(
        answer=out.get("answer", ""),
        citations=out.get("citations", []),
        abstain=out.get("trace", {}).get("abstain", {}),
        trace_id=out.get("trace", {}).get("trace_id", ""),
        n_chunks=len(out.get("chunks", [])),
        trace=out.get("trace", {}) or {},
        memory=(out.get("trace", {}) or {}).get("memory"),
    )


@router.post("/discovery/run")
async def run_discovery(
    body: DiscoveryRunRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Run a bounded paper discovery loop for a research topic."""
    _ensure_paper_rag_importable()
    try:
        from paper_rag.discovery import runner
    except ImportError as e:
        raise HTTPException(503, f"paper_rag.discovery unavailable: {e}")

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
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("paper_rag discovery failed")
        raise HTTPException(503, f"paper_rag discovery unavailable: {e}")


@router.get("/discovery/runs")
async def list_discovery_runs(
    user_id: str = Depends(get_current_user_id),
    limit: int = 20,
) -> list[dict[str, Any]]:
    _ensure_paper_rag_importable()
    try:
        from paper_rag.discovery import store
    except ImportError as e:
        raise HTTPException(503, f"paper_rag.discovery unavailable: {e}")
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
    except ImportError as e:
        raise HTTPException(503, f"paper_rag.discovery unavailable: {e}")
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: store.get_run(run_id, user_id=user_id))
    except KeyError as e:
        raise HTTPException(404, str(e))


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
    except ImportError as e:
        raise HTTPException(503, f"paper_rag.discovery unavailable: {e}")
    force = body.force if body else False
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: runner.ingest_candidate(candidate_id, user_id=user_id, force=force),
        )
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("paper_rag discovery candidate ingest failed")
        raise HTTPException(503, f"paper_rag candidate ingest unavailable: {e}")


@router.get("/papers", response_model=list[PaperRow])
async def list_papers(
    user_id: str = Depends(get_current_user_id),
    limit: int = 100,
) -> list[PaperRow]:
    """List the user's ingested papers (plus the shared 'system' library)."""
    _ensure_paper_rag_importable()
    try:
        # paper_rag.store.sqlite_store keeps the canonical paper list
        from paper_rag.store import sqlite_store
    except ImportError as e:
        raise HTTPException(503, f"paper_rag unavailable: {e}")

    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, _list_papers_for_user, sqlite_store, user_id, limit)
    return [PaperRow(**r) for r in rows]


def _list_papers_for_user(store, user_id: str, limit: int) -> list[dict]:
    """Read papers visible to user_id (their own + 'system' shared library).

    Schema-agnostic: tries to read user_id column if present, falls back to
    listing all papers (legacy path before ADR-0015 schema migration).
    """
    import sqlite3

    sqlite_path = store.SQLITE_PATH if hasattr(store, "SQLITE_PATH") else _resolve_sqlite_path()
    if not Path(sqlite_path).exists():
        return []
    con = sqlite3.connect(str(sqlite_path))
    con.row_factory = sqlite3.Row
    try:
        # SQLModel uses singular table names by default: paper / chunk / section.
        # Detect which table name exists at runtime — robust across both styles.
        table_names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        papers_table = "paper" if "paper" in table_names else "papers"
        chunks_table = "chunk" if "chunk" in table_names else "chunks"
        if papers_table not in table_names:
            return []

        cols = {r[1] for r in con.execute(f"PRAGMA table_info({papers_table})")}
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
        rows = []
        for r in cur:
            paper_id = r["paper_id"]
            cnt = con.execute(
                f"SELECT COUNT(*) AS n FROM {chunks_table} WHERE paper_id = ?",
                (paper_id,),
            ).fetchone()["n"]
            rows.append({
                "paper_id": paper_id,
                "title": r["title"],
                "arxiv_id": r["arxiv_id"],
                "n_chunks": int(cnt or 0),
                "ingested_at": str(r["created_at"]) if r["created_at"] is not None else None,
            })
        return rows
    finally:
        con.close()


def _resolve_sqlite_path() -> str:
    """Find papers.sqlite via paper_rag config."""
    from paper_rag import config as cfg

    return cfg.load().paths.sqlite_path


def _count_qdrant_points(collection: str) -> tuple[int | None, str | None]:
    _ = collection
    return None, "qdrant status unavailable in lightweight integration router"


@router.get("/knowledge/builds", response_model=list[KnowledgeBuildStatus])
async def list_knowledge_builds(
    user_id: str = Depends(get_current_user_id),
    limit: int = 100,
) -> list[KnowledgeBuildStatus]:
    """Return product-facing paper knowledge-base build status."""
    qdrant_points, qdrant_warning = _count_qdrant_points("paper_chunks")
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
    import sqlite3

    wiki_runtime = wiki_runtime or _wiki_runtime_state()
    sqlite_path = _resolve_sqlite_path()
    if not Path(sqlite_path).exists():
        return []
    con = sqlite3.connect(str(sqlite_path))
    con.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        papers_table = "paper" if "paper" in tables else "papers"
        chunks_table = "chunk" if "chunk" in tables else "chunks"
        if papers_table not in tables:
            return []

        cols = {r[1] for r in con.execute(f"PRAGMA table_info({papers_table})")}
        select_cols = [
            "paper_id",
            "title",
            "arxiv_id",
            "created_at",
            "status" if "status" in cols else "NULL AS status",
            "error" if "error" in cols else "NULL AS error",
        ]
        if "user_id" in cols:
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

        rows: list[dict[str, Any]] = []
        for row in cur:
            paper_id = row["paper_id"]
            n_chunks = _kb_count_chunks(con, tables, chunks_table, paper_id)
            steps = _kb_latest_steps(con, tables, paper_id)
            wiki_status = _kb_wiki_status(con, tables, paper_id)
            if wiki_status == "empty" and not bool(wiki_runtime.get("wiki_available")):
                wiki_status = str(wiki_runtime.get("wiki_status") or "unavailable")
            wiki_consumed = _kb_wiki_consumed(con, tables, paper_id)
            wiki_review_needed = _kb_wiki_review_needed(con, tables, paper_id)
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
            rows.append(
                {
                    "paper_id": paper_id,
                    "title": row["title"],
                    "arxiv_id": row["arxiv_id"],
                    "status": row["status"] or "unknown",
                    "error": row["error"],
                    "n_chunks": n_chunks,
                    "ingested_at": str(row["created_at"]) if row["created_at"] is not None else None,
                    "stages": _kb_stages(row, steps, wiki_status),
                    "wiki_status": wiki_status,
                    "wiki_consumed": wiki_consumed,
                    "wiki_review_needed": wiki_review_needed,
                    "qdrant_status": qdrant_status,
                    "warnings": warnings,
                }
            )
        return rows
    finally:
        con.close()


def _kb_count_chunks(con, tables: set[str], chunks_table: str, paper_id: str) -> int:
    if chunks_table not in tables:
        return 0
    row = con.execute(f"SELECT COUNT(*) AS n FROM {chunks_table} WHERE paper_id = ?", (paper_id,)).fetchone()
    return int(row["n"] or 0)


def _kb_latest_steps(con, tables: set[str], paper_id: str) -> dict[str, dict[str, Any]]:
    if "ingest_runs" not in tables:
        return {}
    rows = list(
        con.execute(
            "SELECT step, status, error, finished_at FROM ingest_runs WHERE paper_id = ? ORDER BY id ASC",
            (paper_id,),
        )
    )
    return {
        row["step"]: {
            "status": row["status"] or "pending",
            "error": row["error"],
            "finished_at": str(row["finished_at"]) if row["finished_at"] else None,
        }
        for row in rows
    }


def _kb_wiki_status(con, tables: set[str], paper_id: str) -> str:
    if "wiki_entries" not in tables:
        return "empty"
    for row in con.execute("SELECT key_papers_json FROM wiki_entries"):
        try:
            key_papers = json.loads(row["key_papers_json"] or "[]")
        except Exception:
            key_papers = []
        if paper_id in key_papers:
            return "ready"
    return "empty"


def _kb_wiki_consumed(con, tables: set[str], paper_id: str) -> bool:
    if "wiki_consumption_events" not in tables:
        return False
    try:
        row = con.execute(
            "SELECT 1 FROM wiki_consumption_events WHERE paper_id = ? LIMIT 1",
            (paper_id,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _kb_wiki_review_needed(con, tables: set[str], paper_id: str) -> bool:
    if "wiki_review_queue" not in tables:
        return False
    try:
        row = con.execute(
            "SELECT 1 FROM wiki_review_queue WHERE paper_id = ? AND status = 'pending' LIMIT 1",
            (paper_id,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _kb_stages(row, steps: dict[str, dict[str, Any]], wiki_status: str) -> list[dict[str, Any]]:
    stages = [
        {
            "name": "fetch",
            "status": "error" if row["status"] == "failed" and row["error"] else "ok",
            "error": row["error"] if row["status"] == "failed" and row["error"] else None,
            "finished_at": str(row["created_at"]) if row["created_at"] else None,
        }
    ]
    for name in ("parse", "chunk", "embed", "index"):
        if name in steps:
            stages.append({"name": name, **steps[name]})
        elif row["status"] == "done":
            stages.append({"name": name, "status": "ok", "error": None, "finished_at": None})
        else:
            stages.append({"name": name, "status": "pending", "error": None, "finished_at": None})
    stages.append({"name": "wiki", "status": wiki_status, "error": None, "finished_at": None})
    return stages


@router.post("/papers/ingest", response_model=IngestResponse)
async def ingest_paper(
    body: IngestRequest,
    user_id: str = Depends(get_current_user_id),
) -> IngestResponse:
    """Ingest a paper by arxiv id (preferred) or direct PDF url."""
    if not body.arxiv_id and not body.pdf_url:
        raise HTTPException(400, "Provide either arxiv_id or pdf_url")
    _ensure_paper_rag_importable()
    try:
        from paper_rag.tools.paper_index import ingest as ingest_tool
    except ImportError as e:
        raise HTTPException(503, f"paper_rag unavailable: {e}")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: ingest_tool({
            "arxiv_id": body.arxiv_id,
            "pdf_url": body.pdf_url,
            "title_hint": body.title_hint,
            "user_id": user_id,
        }),
    )
    return IngestResponse(
        paper_id=result.get("paper_id", ""),
        title=result.get("title"),
        n_chunks=int(result.get("n_chunks", 0)),
        status=result.get("status", "ingested"),
    )


@router.get("/wiki/{paper_id}", response_model=WikiResponse)
async def get_wiki(
    paper_id: str,
    user_id: str = Depends(get_current_user_id),
) -> WikiResponse:
    """Return the auto-generated wiki entry for a paper, if available."""
    _ensure_paper_rag_importable()
    try:
        from paper_rag.wiki import store as wiki_store
    except ImportError as e:
        raise HTTPException(503, f"paper_rag unavailable: {e}")

    loop = asyncio.get_running_loop()
    entry = await loop.run_in_executor(None, wiki_store.get, paper_id)
    if not entry:
        raise HTTPException(404, f"No wiki entry for paper_id={paper_id}")
    summary = entry.get("summary", "") if isinstance(entry, dict) else getattr(entry, "summary", "")
    return WikiResponse(
        paper_id=paper_id,
        summary=summary,
        last_updated=str(entry.get("last_updated") if isinstance(entry, dict) else getattr(entry, "last_updated", "")),
        word_count=len(summary.split()),
    )


@router.post("/deliver", response_model=DeliverResponse)
async def deliver(
    body: DeliverRequest,
    user_id: str = Depends(get_current_user_id),
) -> DeliverResponse:
    """Generate a deliverable artifact (Markdown survey / PPT / Word / LaTeX bib).

    See ADR-0016 for the design. The artifact is returned as base64-encoded
    bytes — small enough for survey-class outputs (typical < 200 KB). For
    large multi-paper PPT decks the response can grow; clients should stream
    via /api/paper_rag/deliver/stream when added later.
    """
    import base64

    _ensure_paper_rag_importable()
    try:
        from paper_rag.deliver import dispatch
    except ImportError as e:
        raise HTTPException(503, f"paper_rag.deliver unavailable: {e}")

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
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        # python-pptx / python-docx missing
        raise HTTPException(503, str(e))

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
    """Record a user-behavior feedback event (M11 / ADR-0017).

    Idempotent at minute granularity: re-submitting the same
    (user_id, trace_id, event_type) within the same minute returns the
    existing row id rather than creating a duplicate.
    """
    _ensure_paper_rag_importable()
    try:
        from paper_rag.feedback import record_event
    except ImportError as e:
        raise HTTPException(503, f"paper_rag.feedback unavailable: {e}")

    loop = asyncio.get_running_loop()
    try:
        eid = await loop.run_in_executor(
            None,
            lambda: record_event(
                user_id=user_id,
                event_type=body.event_type,
                payload=body.payload or {},
                trace_id=body.trace_id,
                conversation_id=body.conversation_id,
            ),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(429, str(e))
    return FeedbackResponse(id=eid, status="recorded", user_id=user_id)


@router.get("/feedback/recent")
async def list_recent_feedback(
    user_id: str = Depends(get_current_user_id),
    limit: int = 20,
) -> list[dict[str, Any]]:
    _ensure_paper_rag_importable()
    try:
        from paper_rag.feedback import recent_events
    except ImportError as e:
        raise HTTPException(503, f"paper_rag.feedback unavailable: {e}")

    loop = asyncio.get_running_loop()
    out = await loop.run_in_executor(None, recent_events, user_id, limit)
    return out


@router.get("/feedback/stats")
async def feedback_stats(
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    try:
        from paper_rag.feedback import user_stats
    except ImportError as e:
        raise HTTPException(503, f"paper_rag.feedback unavailable: {e}")

    loop = asyncio.get_running_loop()
    stats = await loop.run_in_executor(None, user_stats, user_id)
    return stats


# ---------------------------------------------------------------------------
# M9 / ADR-0018 — Proactive Agent: subscriptions + inbox + cron triggers
# ---------------------------------------------------------------------------


@router.get("/subscriptions")
async def list_subscriptions(
    user_id: str = Depends(get_current_user_id),
) -> list[dict[str, Any]]:
    _ensure_paper_rag_importable()
    try:
        from paper_rag.proactive import subscriptions
    except ImportError as e:
        raise HTTPException(503, f"paper_rag.proactive unavailable: {e}")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, subscriptions.list_for_user, user_id)


@router.post("/subscriptions")
async def add_subscription(
    body: SubscriptionRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    try:
        from paper_rag.proactive import subscriptions
    except ImportError as e:
        raise HTTPException(503, f"paper_rag.proactive unavailable: {e}")
    loop = asyncio.get_running_loop()
    try:
        sid = await loop.run_in_executor(
            None,
            lambda: subscriptions.add(user_id, body.kind, body.value, strength=body.strength),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": sid, "status": "subscribed"}


@router.delete("/subscriptions/{sub_id}")
async def delete_subscription(
    sub_id: int,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import subscriptions

    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(
        None, lambda: subscriptions.delete(sub_id, user_id=user_id)
    )
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
        None, lambda: subscriptions.toggle(sub_id, enabled=body.enabled, user_id=user_id)
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
        None, lambda: inbox.list_for_user(user_id, unread_only=unread_only, limit=limit)
    )
    unread = await loop.run_in_executor(None, inbox.unread_count, user_id)
    return {"items": items, "unread_count": unread}


@router.post("/inbox/{item_id}/read")
async def mark_inbox_read(
    item_id: int,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import inbox

    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(
        None, lambda: inbox.mark_read(item_id, user_id=user_id)
    )
    return {"id": item_id, "marked_read": ok}


@router.get("/inbox/stream")
async def stream_inbox(
    user_id: str = Depends(get_current_user_id),
    poll_seconds: float = 5.0,
) -> EventSourceResponse:
    """P3-12 / ADR-0018: SSE long-poll for inbox unread items.

    Pushes events of two kinds:
      - ``ping``: heartbeat every poll_seconds (keeps NAT/proxy connections alive)
      - ``inbox``: a single new unread item (one event per item)

    Frontend should subscribe with EventSource and `addEventListener('inbox', ...)`.
    Client closes connection -> server stops the loop.

    This is a poll-based pseudo-push (not full duplex). It avoids needing a
    pub/sub broker while still feeling instant (5s latency upper bound).
    """
    _ensure_paper_rag_importable()
    from paper_rag.proactive import inbox

    poll_seconds = max(1.0, min(float(poll_seconds), 30.0))

    async def _gen() -> AsyncGenerator[dict[str, str], None]:
        loop = asyncio.get_running_loop()
        seen_ids: set[int] = set()
        # Prime: skip everything currently unread (we only push NEW items)
        try:
            existing = await loop.run_in_executor(
                None, lambda: inbox.list_for_user(user_id, unread_only=True, limit=200)
            )
            seen_ids = {int(it["id"]) for it in existing if it.get("id")}
        except Exception:  # noqa: BLE001
            pass

        while True:
            try:
                items = await loop.run_in_executor(
                    None, lambda: inbox.list_for_user(user_id, unread_only=True, limit=50)
                )
            except Exception as e:  # noqa: BLE001 — never crash the stream
                logger.warning("inbox/stream poll failed: %s", e)
                items = []
            for it in items:
                iid = it.get("id")
                if iid is None or int(iid) in seen_ids:
                    continue
                seen_ids.add(int(iid))
                yield {
                    "event": "inbox",
                    "data": json.dumps({
                        "id": iid,
                        "kind": it.get("kind"),
                        "title": it.get("title"),
                        "created_at": it.get("created_at"),
                    }, ensure_ascii=False),
                }
            yield {"event": "ping", "data": json.dumps({"ts": asyncio.get_running_loop().time()})}
            await asyncio.sleep(poll_seconds)

    return EventSourceResponse(_gen())


@router.post("/inbox/{item_id}/dismiss")
async def dismiss_inbox(
    item_id: int,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import inbox

    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(
        None, lambda: inbox.dismiss(item_id, user_id=user_id)
    )
    return {"id": item_id, "dismissed": ok}


@router.post("/proactive/digest/run")
async def run_digest_now(
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Manually trigger digest for the calling user (dev / opt-in)."""
    _ensure_paper_rag_importable()
    from paper_rag.proactive import digest

    loop = asyncio.get_running_loop()
    item_id = await loop.run_in_executor(
        None, lambda: digest.daily_digest_for_user(user_id)
    )
    return {"user_id": user_id, "inbox_item_id": item_id, "wrote": bool(item_id)}


@router.post("/proactive/stale/run")
async def run_stale_now(
    user_id: str = Depends(get_current_user_id),
    days: int = 30,
) -> dict[str, Any]:
    _ensure_paper_rag_importable()
    from paper_rag.proactive import stale

    loop = asyncio.get_running_loop()
    n = await loop.run_in_executor(
        None, lambda: stale.stale_scan_for_user(user_id, older_than_days=days)
    )
    return {"user_id": user_id, "n_cards": n}
