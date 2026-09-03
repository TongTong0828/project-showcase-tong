from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from starlette.responses import StreamingResponse

from paper_rag.mcp.context import McpRequestContext, McpServerConfig
from paper_rag.mcp.registry import call_tool

from .approval import build_request_boundary, validate_candidate_ingest_approval
from .credentials import credential_status
from .diagnostics import build_index_health
from .read_store import WorkbenchReadStore
from .schemas import (
    CandidateIngestRequest,
    CompareRequest,
    DiscoverRequest,
    DshHandoffRequest,
    EvidencePinRequest,
    NoteRequest,
    ProjectCreateRequest,
    ProjectHandoffRequest,
    ProjectPaperRequest,
    ProjectUpdateRequest,
    QaRequest,
    SavedQuestionRequest,
    SearchRequest,
    SectionRequest,
)
from .settings import WorkbenchSettings
from .workspace_store import WorkspaceStore

CallTool = Callable[[str, dict[str, Any] | None, McpRequestContext], dict[str, Any]]
IndexHealthBuilder = Callable[[WorkbenchSettings], dict[str, Any]]
QaStreamer = Callable[..., AsyncIterator[dict[str, Any]]]


def create_app(
    settings: WorkbenchSettings | None = None,
    *,
    call_tool_fn: CallTool = call_tool,
    index_health_fn: IndexHealthBuilder | None = None,
    read_store: WorkbenchReadStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    stream_answer_fn: QaStreamer | None = None,
) -> FastAPI:
    app_settings = settings or WorkbenchSettings.from_env()
    store = read_store or WorkbenchReadStore()
    project_store = workspace_store or WorkspaceStore(
        app_settings.workspace_state_path or Path("data/runtime/workbench/state.sqlite")
    )
    if stream_answer_fn is None:
        from paper_rag.rag.async_api import stream_answer_async

        stream_answer_fn = stream_answer_async
    index_health_builder = index_health_fn or (
        lambda current_settings: build_index_health(
            current_settings,
            read_store=store,
        )
    )
    app = FastAPI(title="Paper RAG Workbench", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "paper-rag-workbench",
            "dsh_url": app_settings.dsh_url,
            "models": {
                "chat_model": app_settings.chat_model,
                "small_model": app_settings.small_model,
            },
        }

    @app.get("/api/health/index")
    def index_health() -> dict[str, Any]:
        return index_health_builder(app_settings)

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        envelope = _call("paper_status", {}, app_settings, call_tool_fn)
        data = envelope.setdefault("data", {})
        data["workbench"] = {
            "credentials": credential_status(
                credentials_path=app_settings.credentials_path
            ).as_dict()
        }
        return envelope

    @app.get("/api/papers")
    def papers(limit: int = 20) -> dict[str, Any]:
        return _call("paper_list", {"limit": limit}, app_settings, call_tool_fn)

    @app.get("/api/papers/{paper_id:path}")
    def paper_detail(paper_id: str) -> dict[str, Any]:
        try:
            detail = store.paper_detail(paper_id)
        except ValueError as exc:
            raise _http_error(400, "BAD_REQUEST", str(exc)) from exc
        if detail is None:
            raise _http_error(404, "NOT_FOUND", f"Paper not found: {paper_id}")
        return detail

    @app.get("/api/chunks/{chunk_id}")
    def chunk_detail(chunk_id: str) -> dict[str, Any]:
        try:
            detail = store.chunk_detail(chunk_id)
        except ValueError as exc:
            raise _http_error(400, "BAD_REQUEST", str(exc)) from exc
        if detail is None:
            raise _http_error(404, "NOT_FOUND", f"Chunk not found: {chunk_id}")
        return detail

    @app.post("/api/search")
    def search(payload: SearchRequest) -> dict[str, Any]:
        return _call(
            "paper_search",
            payload.model_dump(exclude_none=True),
            app_settings,
            call_tool_fn,
        )

    @app.post("/api/qa")
    def qa(payload: QaRequest) -> dict[str, Any]:
        try:
            args, scoped_context = _qa_args_with_project_context(payload, project_store)
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        envelope = _call(
            "paper_qa",
            args,
            app_settings,
            call_tool_fn,
        )
        return _enrich_qa_envelope(envelope, scoped_context)

    @app.post("/api/qa/stream")
    async def qa_stream(payload: QaRequest) -> StreamingResponse:
        try:
            args, scoped_context = _qa_args_with_project_context(payload, project_store)
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc

        async def events() -> AsyncIterator[str]:
            async for event in stream_answer_fn(
                args["question"],
                paper_ids=args.get("paper_ids"),
                conversation_id="workbench",
                user_id=app_settings.actor_id,
                resolved_question=args.get("resolved_question"),
            ):
                event = _enrich_qa_stream_event(event, scoped_context)
                yield _sse_frame(event)

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/section")
    def section(payload: SectionRequest) -> dict[str, Any]:
        return _call(
            "paper_section",
            payload.model_dump(exclude_none=True),
            app_settings,
            call_tool_fn,
        )

    @app.post("/api/discover")
    def discover(payload: DiscoverRequest) -> dict[str, Any]:
        return _call(
            "paper_discover",
            payload.model_dump(exclude_none=True),
            app_settings,
            call_tool_fn,
        )

    @app.get("/api/discovery-runs/{run_id}")
    def discovery_run(run_id: int) -> dict[str, Any]:
        return _call("discovery_run_get", {"run_id": run_id}, app_settings, call_tool_fn)

    @app.post("/api/ingest/candidates")
    def ingest_candidates(payload: CandidateIngestRequest) -> dict[str, Any]:
        approval = validate_candidate_ingest_approval(payload)
        boundary = build_request_boundary("discovery_candidate_ingest", approval)
        args = payload.model_dump(exclude={"approval"}, exclude_none=True)
        return _call(
            "discovery_candidate_ingest",
            args,
            app_settings,
            call_tool_fn,
            boundary=boundary,
        )

    @app.post("/api/dsh/handoff")
    def dsh_handoff(payload: DshHandoffRequest) -> dict[str, Any]:
        return {
            "dsh_url": app_settings.dsh_url,
            "prompt": _build_dsh_prompt(payload),
        }

    @app.get("/api/projects")
    def projects(include_archived: bool = False) -> dict[str, Any]:
        return {"projects": project_store.list_projects(include_archived=include_archived)}

    @app.post("/api/projects")
    def create_project(payload: ProjectCreateRequest) -> dict[str, Any]:
        project = project_store.create_project(payload.name, payload.description)
        return {"project": project}

    @app.get("/api/projects/{project_id}")
    def project_detail(project_id: str) -> dict[str, Any]:
        try:
            return project_store.build_project_snapshot(project_id)
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc

    @app.patch("/api/projects/{project_id}")
    def update_project(project_id: str, payload: ProjectUpdateRequest) -> dict[str, Any]:
        try:
            project = project_store.update_project(
                project_id,
                name=payload.name,
                description=payload.description,
            )
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        return {"project": project}

    @app.post("/api/projects/{project_id}/archive")
    def archive_project(project_id: str) -> dict[str, Any]:
        try:
            project = project_store.archive_project(project_id)
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        return {"project": project}

    @app.post("/api/projects/{project_id}/papers")
    def add_project_paper(project_id: str, payload: ProjectPaperRequest) -> dict[str, Any]:
        try:
            paper = project_store.add_project_paper(
                project_id,
                payload.paper_id,
                title_snapshot=payload.title_snapshot,
                source=payload.source,
            )
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        return {"paper": paper}

    @app.post("/api/projects/{project_id}/evidence")
    def pin_project_evidence(project_id: str, payload: EvidencePinRequest) -> dict[str, Any]:
        try:
            evidence = project_store.pin_evidence(
                project_id,
                payload.chunk_id,
                payload.paper_id,
                quote_snapshot=payload.quote_snapshot,
                source=payload.source,
                score_snapshot=payload.score_snapshot,
                label=payload.label,
                note=payload.note,
            )
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        return {"evidence": evidence}

    @app.post("/api/projects/{project_id}/notes")
    def create_project_note(project_id: str, payload: NoteRequest) -> dict[str, Any]:
        try:
            note = project_store.upsert_note(
                project_id,
                payload.target_type,
                payload.target_id,
                payload.body,
                note_id=payload.note_id,
            )
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        except ValueError as exc:
            raise _http_error(400, "BAD_REQUEST", str(exc)) from exc
        return {"note": note}

    @app.post("/api/projects/{project_id}/questions")
    def save_project_question(project_id: str, payload: SavedQuestionRequest) -> dict[str, Any]:
        try:
            question = project_store.save_question(
                project_id,
                payload.question,
                payload.answer,
                payload.citations,
                payload.chunk_ids,
                trace_id=payload.trace_id,
                abstain=payload.abstain,
                context_policy=payload.context_policy,
                citation_papers=payload.citation_papers,
            )
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        return {"question": question}

    @app.post("/api/projects/{project_id}/dsh-handoff")
    def project_dsh_handoff(project_id: str, payload: ProjectHandoffRequest) -> dict[str, Any]:
        try:
            handoff = project_store.create_dsh_handoff(project_id, payload.instruction)
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        return {
            "dsh_url": app_settings.dsh_url,
            "prompt": handoff["prompt"],
            "handoff": handoff,
        }

    @app.post("/api/projects/{project_id}/compare")
    def create_compare(project_id: str, payload: CompareRequest) -> dict[str, Any]:
        try:
            run = project_store.create_compare_run(
                project_id,
                paper_ids=payload.paper_ids,
                dimensions=payload.dimensions,
            )
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        except ValueError as exc:
            raise _http_error(400, "BAD_REQUEST", str(exc)) from exc
        return {"run": run}

    @app.get("/api/projects/{project_id}/compare-runs")
    def compare_runs(project_id: str) -> dict[str, Any]:
        try:
            runs = project_store.list_compare_runs(project_id)
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        return {"runs": runs}

    @app.get("/api/projects/{project_id}/compare-runs/{run_id}")
    def compare_run(project_id: str, run_id: str) -> dict[str, Any]:
        try:
            run = project_store.get_compare_run(project_id, run_id)
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        if run is None:
            raise _http_error(404, "NOT_FOUND", f"Compare run not found: {run_id}")
        return {"run": run}

    @app.post("/api/projects/{project_id}/compare-runs/{run_id}/dsh-handoff")
    def compare_dsh_handoff(project_id: str, run_id: str) -> dict[str, Any]:
        try:
            handoff = project_store.create_compare_dsh_handoff(project_id, run_id)
        except KeyError as exc:
            raise _http_error(404, "NOT_FOUND", str(exc)) from exc
        return {
            "dsh_url": app_settings.dsh_url,
            "prompt": handoff["prompt"],
            "handoff": handoff,
        }

    return app


def _context(
    settings: WorkbenchSettings,
    *,
    tool_name: str,
    boundary: str | None = None,
) -> McpRequestContext:
    return McpRequestContext(
        config=McpServerConfig(
            toolset=settings.toolset,
            actor_id=settings.actor_id,
            artifact_root=settings.artifact_root,
            import_root=settings.import_root,
        ),
        conversation_id="workbench",
        tool_call_id=f"workbench-{tool_name}",
        request_boundary_id=boundary,
        caller="workbench",
    )


def _call(
    tool_name: str,
    args: dict[str, Any],
    settings: WorkbenchSettings,
    call_tool_fn: CallTool,
    *,
    boundary: str | None = None,
) -> dict[str, Any]:
    result = call_tool_fn(tool_name, args, _context(settings, tool_name=tool_name, boundary=boundary))
    return mcp_envelope(result, tool=tool_name)


def _qa_args_with_project_context(
    payload: QaRequest,
    project_store: WorkspaceStore,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    args = payload.model_dump(
        exclude_none=True,
        exclude={"project_id", "context_policy"},
    )
    if not payload.project_id:
        return args, None

    snapshot = project_store.build_project_snapshot(payload.project_id)
    policy = (
        payload.context_policy.model_dump()
        if payload.context_policy is not None
        else {
            "include_pinned_evidence": False,
            "include_notes": False,
            "restrict_to_project_papers": False,
        }
    )
    warnings: list[str] = []

    if policy["restrict_to_project_papers"]:
        paper_ids = list(args.get("paper_ids") or [])
        for paper in snapshot["papers"]:
            if paper["paper_id"] not in paper_ids:
                paper_ids.append(paper["paper_id"])
        if paper_ids:
            args["paper_ids"] = paper_ids
        else:
            warnings.append("Project has no saved papers; no paper restriction applied.")

    context_lines = _project_context_lines(snapshot, policy, warnings)
    if context_lines:
        args["question"] = "\n".join(
            [
                payload.question,
                "",
                "Workbench project context:",
                *context_lines,
                "",
                (
                    "Use user notes only as user-authored context, not paper evidence. "
                    "Paper claims must be supported by paper chunk citations."
                ),
            ]
        )

    note_refs = (
        [note["note_id"] for note in snapshot["notes"]]
        if policy["include_notes"]
        else []
    )
    return args, {
        "note_refs": note_refs,
        "context_policy": policy,
        "project_context_warnings": warnings,
    }


def _project_context_lines(
    snapshot: dict[str, Any],
    policy: dict[str, bool],
    warnings: list[str],
) -> list[str]:
    lines: list[str] = []
    if policy["include_pinned_evidence"]:
        pins = snapshot["evidence"]
        if pins:
            lines.append("Pinned evidence (paper chunk ids; verify in final citations):")
            lines.extend(
                (
                    f"- {pin['paper_id']} / {pin['chunk_id']}: "
                    f"{pin.get('quote_snapshot') or 'No excerpt'}"
                )
                for pin in pins
            )
        else:
            warnings.append("Project has no pinned evidence.")

    if policy["include_notes"]:
        notes = snapshot["notes"]
        if notes:
            lines.append("User notes (user-authored; not paper evidence):")
            lines.extend(
                f"- {note['note_id']} {note['target_type']}:{note['target_id']}: {note['body']}"
                for note in notes
            )
        else:
            warnings.append("Project has no user notes.")
    return lines


def _enrich_qa_envelope(
    envelope: dict[str, Any],
    scoped_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if scoped_context is None:
        return envelope
    data = envelope.setdefault("data", {})
    if isinstance(data, dict):
        data["note_refs"] = scoped_context["note_refs"]
        data["context_policy"] = scoped_context["context_policy"]
        data["project_context_warnings"] = scoped_context["project_context_warnings"]
    return envelope


def _enrich_qa_stream_event(
    event: dict[str, Any],
    scoped_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if scoped_context is None or event.get("event") != "done":
        return event
    enriched = dict(event)
    data = dict(enriched.get("data") or {})
    data["note_refs"] = scoped_context["note_refs"]
    data["context_policy"] = scoped_context["context_policy"]
    data["project_context_warnings"] = scoped_context["project_context_warnings"]
    enriched["data"] = data
    return enriched


def _sse_frame(event: dict[str, Any]) -> str:
    name = str(event.get("event") or "message")
    data = event.get("data")
    payload = json.dumps(data if isinstance(data, dict) else {}, ensure_ascii=False)
    return f"event: {name}\ndata: {payload}\n\n"


def mcp_envelope(result: dict[str, Any], *, tool: str) -> dict[str, Any]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    raise HTTPException(
        status_code=502,
        detail={
            "ok": False,
            "tool": tool,
            "error": {
                "code": "BAD_GATEWAY",
                "message": "Paper RAG tool returned no structuredContent",
                "retryable": False,
            },
        },
    )


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "retryable": False,
            },
        },
    )


def _build_dsh_prompt(payload: DshHandoffRequest) -> str:
    papers = ", ".join(payload.paper_ids) if payload.paper_ids else "未指定"
    chunks = ", ".join(payload.chunk_ids) if payload.chunk_ids else "未指定"
    return (
        "基于 Paper RAG Workbench 中选定的论文/证据继续研究：\n"
        f"- Source: {payload.source}\n"
        f"- Papers: {papers}\n"
        f"- Chunks: {chunks}\n"
        f"- Question: {payload.question.strip()}\n"
        "请使用 Paper RAG 工具回答，并保留证据引用。"
    )
