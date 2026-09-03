# Paper RAG Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent local Paper RAG Workbench with visual corpus, search, cited QA, discovery, and approval-gated ingestion workflows while preserving DSH Web as the agent chat and trace surface.

**Architecture:** The Workbench is a separate Vite/React SPA backed by a thin FastAPI adapter. The adapter validates HTTP input, builds trusted `McpRequestContext` values, calls `paper_rag.mcp.registry.call_tool(...)`, and returns existing MCP envelopes without duplicating Paper RAG business logic. DSH Web and the `Paper Research` preset continue to use the same Paper RAG kernel through the existing native broker.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, pytest, React 18, TypeScript, Vite, Vitest, React Testing Library, Playwright, `paper_rag.mcp.registry`, `deepseek-v4-flash`.

## Global Constraints

- Provide a dedicated local web UI for the Paper RAG research workflow.
- Preserve the migrated runtime: no DeerFlow host, gateway, workspace, or smoke path returns.
- Reuse the existing MCP registry and `src/paper_rag` kernel as the single source of paper operations.
- Make the core workflow visible without requiring prompt-only interaction: overview, library, evidence search, cited QA, discovery, and approved ingest.
- Keep DSH Web available as the agent chat, trace, and session-log companion.
- Keep `deepseek-v4-flash` as the model target.
- Keep write operations explicit and approval-gated.
- Keep secrets, real PDFs, runtime credentials, `data/index`, and generated runtime state out of git.
- Do not embed this UI inside DSH Web or depend on private DSH frontend internals.
- Do not remove DSH Web, the `Paper Research` preset, or DSH trace/session workflows.
- Do not recreate DeerFlow auth, gateway middleware, dashboard, or deployment topology.
- Do not add multi-user SaaS authentication in the first Workbench release.
- Do not build Compare or Deliverables as first-class MVP screens.
- Do not perform automated live smoke writes against the real paper library without explicit user approval.
- Workbench UI runs on `http://127.0.0.1:3090`; Workbench API runs on `http://127.0.0.1:3091`.
- DSH Web remains on `http://127.0.0.1:3080` by default.
- The launcher must set `OPENAI_BASE_URL=https://api.deepseek.com`, `CHAT_MODEL=deepseek-v4-flash`, and `SMALL_MODEL=deepseek-v4-flash`.
- The Workbench must not switch to a pro model.
- Write smoke must use isolated data paths unless the user explicitly approves writing to the real library.
- Required final validation: Python tests, frontend tests, Playwright smoke, DSH integration tests, affected migration validators, `scripts/secret_scan.py`, and clean git status.

---

## Scope Check

This is one coherent product slice. It contains two technical layers, but each layer is in service of the same Workbench MVP:

- FastAPI adapter: exposes existing Paper RAG MCP tools to the browser with trusted context and approval boundaries.
- React SPA: renders the Workbench product screens against that adapter.

Compare, Deliverables, shared Workbench/DSH sessions, data quality dashboards, subscriptions, and proactive inbox views are out of this implementation plan.

## Current State Map

- Approved spec: `docs/superpowers/specs/2026-08-14-paper-rag-workbench-design.md`.
- Existing MCP registry: `src/paper_rag/mcp/registry.py`.
- Existing MCP context types: `src/paper_rag/mcp/context.py`.
- Existing DSH frontend integration: `integrations/deepseek-harness/`.
- Existing DSH Web start command: `pnpm --dir integrations/deepseek-harness start`.
- Existing secret scanner: `scripts/secret_scan.py`.
- Existing Python dev extra includes FastAPI but does not list Uvicorn yet.
- No Workbench app exists yet.

## File Structure

Backend files:

- Create `src/paper_rag/workbench/__init__.py`: package marker and public exports.
- Create `src/paper_rag/workbench/settings.py`: `WorkbenchSettings` and environment loading.
- Create `src/paper_rag/workbench/schemas.py`: HTTP request/response Pydantic models.
- Create `src/paper_rag/workbench/credentials.py`: credential status detection and secret-safe redaction.
- Create `src/paper_rag/workbench/approval.py`: approval payload validation and request-boundary creation.
- Create `src/paper_rag/workbench/api.py`: FastAPI `create_app(...)`, route registration, MCP adapter call helpers.
- Create `src/paper_rag/workbench/__main__.py`: `python -m paper_rag.workbench` development server entrypoint.
- Modify `pyproject.toml`: add `uvicorn>=0.30` to the `dev` optional dependency group.
- Create `tests/test_workbench_api.py`: backend route, approval, credential, and envelope tests.

Frontend files:

- Create `integrations/paper-rag-workbench/package.json`: scripts and dependencies.
- Create `integrations/paper-rag-workbench/tsconfig.json`: TypeScript app config.
- Create `integrations/paper-rag-workbench/tsconfig.node.json`: Vite config TypeScript config.
- Create `integrations/paper-rag-workbench/vite.config.ts`: Vite dev server, `/api` proxy, Vitest config.
- Create `integrations/paper-rag-workbench/playwright.config.ts`: fixture-mode Playwright config.
- Create `integrations/paper-rag-workbench/index.html`: app mount.
- Create `integrations/paper-rag-workbench/src/vite-env.d.ts`: Vite environment types.
- Create `integrations/paper-rag-workbench/src/main.tsx`: React entrypoint.
- Create `integrations/paper-rag-workbench/src/App.tsx`: route state and shell composition.
- Create `integrations/paper-rag-workbench/src/styles.css`: product styling.
- Create `integrations/paper-rag-workbench/src/test/setup.ts`: Vitest DOM matcher setup.
- Create `integrations/paper-rag-workbench/src/types.ts`: MCP envelope and domain view types.
- Create `integrations/paper-rag-workbench/src/api/client.ts`: API client with fixture mode.
- Create `integrations/paper-rag-workbench/src/api/fixtures.ts`: deterministic fixture responses.
- Create `integrations/paper-rag-workbench/src/components/Shell.tsx`: navigation, header, DSH bridge.
- Create `integrations/paper-rag-workbench/src/components/StatusBadge.tsx`: status and warning chips.
- Create `integrations/paper-rag-workbench/src/components/PaperTable.tsx`: indexed paper table.
- Create `integrations/paper-rag-workbench/src/components/EvidenceChunkCard.tsx`: evidence chunk rendering.
- Create `integrations/paper-rag-workbench/src/components/CitationChips.tsx`: citation chips.
- Create `integrations/paper-rag-workbench/src/components/AnswerPanel.tsx`: QA answer rendering.
- Create `integrations/paper-rag-workbench/src/components/CandidateTable.tsx`: discovery candidate table.
- Create `integrations/paper-rag-workbench/src/components/ApprovalDialog.tsx`: approval modal.
- Create `integrations/paper-rag-workbench/src/components/EmptyState.tsx`: actionable empty/error states.
- Create `integrations/paper-rag-workbench/src/pages/OverviewPage.tsx`: corpus overview.
- Create `integrations/paper-rag-workbench/src/pages/LibraryPage.tsx`: library filter and section drawer.
- Create `integrations/paper-rag-workbench/src/pages/SearchPage.tsx`: evidence search.
- Create `integrations/paper-rag-workbench/src/pages/AskPage.tsx`: cited QA.
- Create `integrations/paper-rag-workbench/src/pages/DiscoverPage.tsx`: candidate discovery and approved ingest.
- Create `integrations/paper-rag-workbench/src/__tests__/client.test.ts`: API client tests.
- Create `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`: shared component tests.
- Create `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`: page workflow tests.
- Create `integrations/paper-rag-workbench/tests/workbench.spec.ts`: Playwright fixture smoke.

Launcher and docs:

- Create `scripts/start_workbench.py`: starts API and SPA dev servers with safe defaults.
- Modify `Makefile`: add `workbench` target.
- Create `integrations/paper-rag-workbench/README.md`: local usage and validation commands.
- Modify root `README.md`: add Workbench quick-start note.

## Shared Interfaces

Backend:

```python
@dataclass(frozen=True)
class WorkbenchSettings:
    actor_id: str
    toolset: str
    dsh_url: str
    credentials_path: Path | None
    artifact_root: Path | None
    import_root: Path | None
    openai_base_url: str
    chat_model: str
    small_model: str

def create_app(
    settings: WorkbenchSettings | None = None,
    *,
    call_tool_fn: Callable[[str, dict[str, Any] | None, McpRequestContext], dict[str, Any]] = call_tool,
) -> FastAPI: ...

def mcp_envelope(result: dict[str, Any], *, tool: str) -> dict[str, Any]: ...

def credential_status(env: Mapping[str, str], credentials_path: Path | None) -> CredentialStatus: ...

def build_request_boundary(tool_name: str, approval: ApprovalPayload) -> str: ...
```

Frontend:

```ts
export type McpEnvelope<TData = Record<string, unknown>> = {
  ok: boolean;
  tool: string;
  trace_id?: string | null;
  evidence_role?: string;
  warnings?: string[];
  data?: TData;
  error?: {
    code: string;
    message: string;
    retryable?: boolean;
    details?: Record<string, unknown>;
  };
};

export type WorkbenchClient = {
  health(): Promise<HealthData>;
  status(): Promise<McpEnvelope<StatusData>>;
  papers(limit?: number): Promise<McpEnvelope<PaperListData>>;
  search(input: SearchInput): Promise<McpEnvelope<SearchData>>;
  qa(input: QaInput): Promise<McpEnvelope<QaData>>;
  section(input: SectionInput): Promise<McpEnvelope<SectionData>>;
  discover(input: DiscoverInput): Promise<McpEnvelope<DiscoverData>>;
  ingestCandidates(input: CandidateIngestInput): Promise<McpEnvelope<IngestData>>;
};
```

---

## Task 1: Workbench API Settings, Schemas, And App Factory

**Files:**
- Create: `src/paper_rag/workbench/__init__.py`
- Create: `src/paper_rag/workbench/settings.py`
- Create: `src/paper_rag/workbench/schemas.py`
- Create: `src/paper_rag/workbench/api.py`
- Modify: `pyproject.toml`
- Test: `tests/test_workbench_api.py`

**Interfaces:**
- Produces: `WorkbenchSettings.from_env(env: Mapping[str, str] | None = None) -> WorkbenchSettings`
- Produces: `create_app(settings: WorkbenchSettings | None = None, *, call_tool_fn=call_tool) -> FastAPI`
- Produces: `mcp_envelope(result: dict[str, Any], *, tool: str) -> dict[str, Any]`
- Consumes: `paper_rag.mcp.registry.call_tool(name, args, ctx)`
- Consumes: `paper_rag.mcp.context.McpRequestContext` and `McpServerConfig`

- [ ] **Step 1: Write failing backend app tests**

Create `tests/test_workbench_api.py` with the first tests:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


def _settings(tmp_path: Path):
    from paper_rag.workbench.settings import WorkbenchSettings

    return WorkbenchSettings(
        actor_id="workbench",
        toolset="research",
        dsh_url="http://127.0.0.1:3080",
        credentials_path=tmp_path / ".credentials.yaml",
        artifact_root=tmp_path / "artifacts",
        import_root=tmp_path / "imports",
        openai_base_url="https://api.deepseek.com",
        chat_model="deepseek-v4-flash",
        small_model="deepseek-v4-flash",
    )


def test_health_reports_workbench_model_and_dsh_url(tmp_path):
    from paper_rag.workbench.api import create_app

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=lambda *_args: {}))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "paper-rag-workbench",
        "dsh_url": "http://127.0.0.1:3080",
        "models": {
            "chat_model": "deepseek-v4-flash",
            "small_model": "deepseek-v4-flash",
        },
    }


def test_status_endpoint_returns_mcp_structured_content(tmp_path):
    from paper_rag.workbench.api import create_app

    seen: dict[str, Any] = {}

    def fake_call_tool(name, args, ctx):
        seen.update(
            name=name,
            args=args,
            actor_id=ctx.actor_id,
            toolset=ctx.config.toolset,
            conversation_id=ctx.conversation_id,
            tool_call_id=ctx.tool_call_id,
        )
        return {
            "structuredContent": {
                "ok": True,
                "tool": "paper_status",
                "evidence_role": "metadata",
                "warnings": [],
                "data": {
                    "sqlite": {"paper_count": 2, "chunk_count": 30, "available": True},
                    "llm": {"chat_model": "deepseek-v4-flash", "configured": True},
                },
            }
        }

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=fake_call_tool))

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["tool"] == "paper_status"
    assert response.json()["data"]["sqlite"]["paper_count"] == 2
    assert seen == {
        "name": "paper_status",
        "args": {},
        "actor_id": "workbench",
        "toolset": "research",
        "conversation_id": "workbench",
        "tool_call_id": "workbench-paper_status",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_workbench_api.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'paper_rag.workbench'`.

- [ ] **Step 3: Add `uvicorn` to dev dependencies**

Modify the `dev` optional dependency list in `pyproject.toml`:

```toml
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
    "pre-commit>=3.7",
    "fastapi>=0.115",
    "uvicorn>=0.30",
]
```

- [ ] **Step 4: Create Workbench settings**

Create `src/paper_rag/workbench/settings.py`:

```python
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkbenchSettings:
    actor_id: str = "workbench"
    toolset: str = "research"
    dsh_url: str = "http://127.0.0.1:3080"
    credentials_path: Path | None = None
    artifact_root: Path | None = None
    import_root: Path | None = None
    openai_base_url: str = "https://api.deepseek.com"
    chat_model: str = "deepseek-v4-flash"
    small_model: str = "deepseek-v4-flash"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "WorkbenchSettings":
        source = os.environ if env is None else env
        credentials = source.get("PAPER_RAG_DSH_CREDENTIALS_PATH")
        artifact_root = source.get("PAPER_RAG_ARTIFACT_ROOT")
        import_root = source.get("PAPER_RAG_IMPORT_ROOT")
        return cls(
            actor_id=source.get("PAPER_RAG_WORKBENCH_ACTOR_ID", "workbench"),
            toolset=source.get("PAPER_RAG_WORKBENCH_TOOLSET", "research"),
            dsh_url=source.get("PAPER_RAG_DSH_URL", "http://127.0.0.1:3080"),
            credentials_path=Path(credentials).resolve() if credentials else None,
            artifact_root=Path(artifact_root).resolve() if artifact_root else None,
            import_root=Path(import_root).resolve() if import_root else None,
            openai_base_url=source.get("OPENAI_BASE_URL", "https://api.deepseek.com"),
            chat_model=source.get("CHAT_MODEL", "deepseek-v4-flash"),
            small_model=source.get("SMALL_MODEL", source.get("CHAT_MODEL", "deepseek-v4-flash")),
        )
```

- [ ] **Step 5: Create request schemas**

Create `src/paper_rag/workbench/schemas.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchRequest(StrictRequest):
    query: str
    top_k: int = Field(8, ge=1, le=30)
    year_min: int | None = None
    year_max: int | None = None


class QaRequest(StrictRequest):
    question: str
    paper_ids: list[str] | None = None
    resolved_question: str | None = None
    top_k: int = Field(8, ge=1, le=20)


class SectionRequest(StrictRequest):
    paper_id: str
    section_name: str


class DiscoverRequest(StrictRequest):
    topic: str
    max_candidates: int = Field(10, ge=1, le=20)
    sources: list[str] | None = None


class ApprovalPayload(StrictRequest):
    approved: bool
    operation: str
    candidate_ids: list[int] = Field(default_factory=list)
    destination: str
    side_effects: list[str] = Field(default_factory=list)


class CandidateIngestRequest(StrictRequest):
    candidate_ids: list[int] = Field(..., min_length=1, max_length=5)
    force: bool = False
    approval: ApprovalPayload | None = None


McpEnvelope = dict[str, Any]
```

- [ ] **Step 6: Create app factory and read routes**

Create `src/paper_rag/workbench/api.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException

from paper_rag.mcp.context import McpRequestContext, McpServerConfig
from paper_rag.mcp.registry import call_tool

from .schemas import DiscoverRequest, QaRequest, SearchRequest, SectionRequest
from .settings import WorkbenchSettings

CallTool = Callable[[str, dict[str, Any] | None, McpRequestContext], dict[str, Any]]


def create_app(
    settings: WorkbenchSettings | None = None,
    *,
    call_tool_fn: CallTool = call_tool,
) -> FastAPI:
    app_settings = settings or WorkbenchSettings.from_env()
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

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return _call("paper_status", {}, app_settings, call_tool_fn)

    @app.get("/api/papers")
    def papers(limit: int = 20) -> dict[str, Any]:
        return _call("paper_list", {"limit": limit}, app_settings, call_tool_fn)

    @app.post("/api/search")
    def search(payload: SearchRequest) -> dict[str, Any]:
        return _call("paper_search", payload.model_dump(exclude_none=True), app_settings, call_tool_fn)

    @app.post("/api/qa")
    def qa(payload: QaRequest) -> dict[str, Any]:
        return _call("paper_qa", payload.model_dump(exclude_none=True), app_settings, call_tool_fn)

    @app.post("/api/section")
    def section(payload: SectionRequest) -> dict[str, Any]:
        return _call("paper_section", payload.model_dump(exclude_none=True), app_settings, call_tool_fn)

    @app.post("/api/discover")
    def discover(payload: DiscoverRequest) -> dict[str, Any]:
        return _call("paper_discover", payload.model_dump(exclude_none=True), app_settings, call_tool_fn)

    @app.get("/api/discovery-runs/{run_id}")
    def discovery_run(run_id: int) -> dict[str, Any]:
        return _call("discovery_run_get", {"run_id": run_id}, app_settings, call_tool_fn)

    return app


def _context(settings: WorkbenchSettings, *, tool_name: str, boundary: str | None = None) -> McpRequestContext:
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


def _call(tool_name: str, args: dict[str, Any], settings: WorkbenchSettings, call_tool_fn: CallTool) -> dict[str, Any]:
    result = call_tool_fn(tool_name, args, _context(settings, tool_name=tool_name))
    return mcp_envelope(result, tool=tool_name)


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
```

- [ ] **Step 7: Export public app interfaces**

Create `src/paper_rag/workbench/__init__.py`:

```python
"""Local Paper RAG Workbench API adapter."""

from .api import create_app
from .settings import WorkbenchSettings

__all__ = ["WorkbenchSettings", "create_app"]
```

- [ ] **Step 8: Run backend tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_workbench_api.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/paper_rag/workbench tests/test_workbench_api.py
git commit -m "feat: add workbench api foundation"
```

## Task 2: Credential Status Redaction And Write Approval Boundary

**Files:**
- Create: `src/paper_rag/workbench/credentials.py`
- Create: `src/paper_rag/workbench/approval.py`
- Modify: `src/paper_rag/workbench/api.py`
- Modify: `tests/test_workbench_api.py`

**Interfaces:**
- Produces: `CredentialStatus(configured: bool, source: str | None, writable: bool)`
- Produces: `credential_status(env: Mapping[str, str], credentials_path: Path | None) -> CredentialStatus`
- Produces: `validate_candidate_ingest_approval(payload: CandidateIngestRequest) -> ApprovalPayload`
- Produces: `build_request_boundary(tool_name: str, approval: ApprovalPayload) -> str`
- Modifies: `GET /api/status` to include secret-safe `workbench.credentials`
- Adds: `POST /api/ingest/candidates`

- [ ] **Step 1: Add failing credential and approval tests**

Append these tests to `tests/test_workbench_api.py`:

```python
def test_status_reports_credential_source_without_secret(tmp_path, monkeypatch):
    from paper_rag.workbench.api import create_app

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret-value")

    def fake_call_tool(name, args, ctx):
        return {
            "structuredContent": {
                "ok": True,
                "tool": "paper_status",
                "evidence_role": "metadata",
                "warnings": [],
                "data": {"llm": {"chat_model": "deepseek-v4-flash", "configured": True}},
            }
        }

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=fake_call_tool))

    payload = client.get("/api/status").json()

    assert payload["data"]["workbench"]["credentials"] == {
        "configured": True,
        "source": "env",
        "writable": False,
    }
    assert "sk-test-secret-value" not in str(payload)


def test_candidate_ingest_rejects_missing_approval(tmp_path):
    from paper_rag.workbench.api import create_app

    calls = []

    def fake_call_tool(name, args, ctx):
        calls.append((name, args, ctx))
        return {"structuredContent": {"ok": True, "tool": name, "data": {}}}

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=fake_call_tool))

    response = client.post("/api/ingest/candidates", json={"candidate_ids": [11]})

    assert response.status_code == 403
    assert response.json()["detail"]["error"]["code"] == "APPROVAL_REQUIRED"
    assert calls == []


def test_candidate_ingest_passes_request_boundary_after_approval(tmp_path):
    from paper_rag.workbench.api import create_app

    seen = {}

    def fake_call_tool(name, args, ctx):
        seen.update(
            name=name,
            args=args,
            request_boundary_id=ctx.request_boundary_id,
            conversation_id=ctx.conversation_id,
            tool_call_id=ctx.tool_call_id,
        )
        return {
            "structuredContent": {
                "ok": True,
                "tool": "discovery_candidate_ingest",
                "evidence_role": "metadata",
                "warnings": [],
                "data": {"results": [{"candidate_id": 11, "paper_id": "paper-11", "status": "ingested"}]},
            }
        }

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=fake_call_tool))

    response = client.post(
        "/api/ingest/candidates",
        json={
            "candidate_ids": [11],
            "force": False,
            "approval": {
                "approved": True,
                "operation": "discovery_candidate_ingest",
                "candidate_ids": [11],
                "destination": "real-library",
                "side_effects": ["write indexed paper and chunks"],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["results"][0]["paper_id"] == "paper-11"
    assert seen["name"] == "discovery_candidate_ingest"
    assert seen["args"] == {"candidate_ids": [11], "force": False}
    assert seen["request_boundary_id"].startswith("workbench-discovery_candidate_ingest-")
    assert seen["conversation_id"] == "workbench"
    assert seen["tool_call_id"] == "workbench-discovery_candidate_ingest"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_workbench_api.py
```

Expected: FAIL because credential helpers and `/api/ingest/candidates` are missing.

- [ ] **Step 3: Implement credential status detection**

Create `src/paper_rag/workbench/credentials.py`:

```python
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CredentialStatus:
    configured: bool
    source: str | None
    writable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "source": self.source,
            "writable": self.writable,
        }


def credential_status(
    env: Mapping[str, str] | None = None,
    credentials_path: Path | None = None,
) -> CredentialStatus:
    source = os.environ if env is None else env
    if source.get("DEEPSEEK_API_KEY") or source.get("OPENAI_API_KEY"):
        return CredentialStatus(configured=True, source="env", writable=False)
    if credentials_path is not None and credentials_path.exists():
        text = credentials_path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        if isinstance(data, dict) and (data.get("DEEPSEEK_API_KEY") or data.get("OPENAI_API_KEY")):
            return CredentialStatus(configured=True, source="file", writable=True)
    return CredentialStatus(configured=False, source=None, writable=True)
```

- [ ] **Step 4: Implement approval boundary helpers**

Create `src/paper_rag/workbench/approval.py`:

```python
from __future__ import annotations

from hashlib import sha256

from fastapi import HTTPException

from .schemas import ApprovalPayload, CandidateIngestRequest


def validate_candidate_ingest_approval(payload: CandidateIngestRequest) -> ApprovalPayload:
    approval = payload.approval
    if approval is None or approval.approved is not True:
        raise _approval_error("Candidate ingestion requires explicit approval.")
    if approval.operation != "discovery_candidate_ingest":
        raise _approval_error("Approval operation must be discovery_candidate_ingest.")
    if approval.candidate_ids != payload.candidate_ids:
        raise _approval_error("Approved candidate ids must match the ingest request.")
    if approval.destination not in {"real-library", "isolated-library"}:
        raise _approval_error("Approval destination must be real-library or isolated-library.")
    if not approval.side_effects:
        raise _approval_error("Approval must include side effects.")
    return approval


def build_request_boundary(tool_name: str, approval: ApprovalPayload) -> str:
    digest = sha256(
        f"{tool_name}|{approval.destination}|{','.join(map(str, approval.candidate_ids))}".encode("utf-8")
    ).hexdigest()[:16]
    return f"workbench-{tool_name}-{digest}"


def _approval_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "ok": False,
            "tool": "discovery_candidate_ingest",
            "error": {
                "code": "APPROVAL_REQUIRED",
                "message": message,
                "retryable": False,
            },
        },
    )
```

- [ ] **Step 5: Wire credentials and approved ingest into API**

Modify `src/paper_rag/workbench/api.py`:

```python
from .approval import build_request_boundary, validate_candidate_ingest_approval
from .credentials import credential_status
from .schemas import CandidateIngestRequest, DiscoverRequest, QaRequest, SearchRequest, SectionRequest
```

Update `/api/status`:

```python
    @app.get("/api/status")
    def status() -> dict[str, Any]:
        envelope = _call("paper_status", {}, app_settings, call_tool_fn)
        data = envelope.setdefault("data", {})
        data["workbench"] = {
            "credentials": credential_status(credentials_path=app_settings.credentials_path).as_dict()
        }
        return envelope
```

Add the write endpoint:

```python
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
```

Change `_call` signature and call site:

```python
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
```

- [ ] **Step 6: Run backend tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_workbench_api.py
```

Expected: PASS.

- [ ] **Step 7: Run related MCP contract tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_mcp_frontend_contract.py tests/test_mcp_tools.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/paper_rag/workbench tests/test_workbench_api.py
git commit -m "feat: protect workbench writes with approval"
```

## Task 3: Workbench Frontend Scaffold, Fixtures, And API Client

**Files:**
- Create: `integrations/paper-rag-workbench/package.json`
- Create: `integrations/paper-rag-workbench/tsconfig.json`
- Create: `integrations/paper-rag-workbench/tsconfig.node.json`
- Create: `integrations/paper-rag-workbench/vite.config.ts`
- Create: `integrations/paper-rag-workbench/playwright.config.ts`
- Create: `integrations/paper-rag-workbench/index.html`
- Create: `integrations/paper-rag-workbench/src/main.tsx`
- Create: `integrations/paper-rag-workbench/src/App.tsx`
- Create: `integrations/paper-rag-workbench/src/styles.css`
- Create: `integrations/paper-rag-workbench/src/types.ts`
- Create: `integrations/paper-rag-workbench/src/api/client.ts`
- Create: `integrations/paper-rag-workbench/src/api/fixtures.ts`
- Create: `integrations/paper-rag-workbench/src/__tests__/client.test.ts`

**Interfaces:**
- Produces: `createWorkbenchClient(options?: { baseUrl?: string; fixtureMode?: boolean; fetchImpl?: typeof fetch }): WorkbenchClient`
- Produces: deterministic fixture envelopes for all MVP routes.
- Produces: Vite app shell that renders "Paper RAG Workbench" and navigation labels.

- [ ] **Step 1: Create frontend package metadata**

Create `integrations/paper-rag-workbench/package.json`:

```json
{
  "name": "@paper-rag/workbench",
  "version": "0.0.0",
  "private": true,
  "type": "module",
  "packageManager": "pnpm@11.19.0",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 3090",
    "build": "tsc -p tsconfig.json && vite build",
    "test": "vitest run",
    "test:watch": "vitest",
    "playwright": "playwright test"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^5.0.0",
    "lucide-react": "^0.468.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "vite": "^6.0.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.50.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.9.3",
    "vitest": "^4.0.16"
  }
}
```

- [ ] **Step 2: Add TypeScript and Vite configs**

Create `integrations/paper-rag-workbench/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "types": ["vitest/globals", "@testing-library/jest-dom", "vite/client"],
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `integrations/paper-rag-workbench/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts", "playwright.config.ts"]
}
```

Create `integrations/paper-rag-workbench/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 3090,
    proxy: {
      "/api": "http://127.0.0.1:3091",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    globals: true,
  },
});
```

Create `integrations/paper-rag-workbench/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  use: {
    baseURL: "http://127.0.0.1:3090",
  },
  webServer: {
    command: "VITE_WORKBENCH_FIXTURES=1 pnpm dev",
    url: "http://127.0.0.1:3090",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
```

- [ ] **Step 3: Write failing API client tests**

Create `integrations/paper-rag-workbench/src/__tests__/client.test.ts`:

```ts
import { describe, expect, test, vi } from "vitest";

import { createWorkbenchClient } from "../api/client";

describe("Workbench API client", () => {
  test("uses fixture responses without touching fetch", async () => {
    const fetchImpl = vi.fn();
    const client = createWorkbenchClient({ fixtureMode: true, fetchImpl: fetchImpl as never });

    const status = await client.status();
    const qa = await client.qa({ question: "What is Self-RAG?", top_k: 5 });

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(status.tool).toBe("paper_status");
    expect(status.data?.sqlite.paper_count).toBeGreaterThan(0);
    expect(qa.tool).toBe("paper_qa");
    expect(qa.data?.citations).toContain("chunk-self-rag-1");
  });

  test("posts JSON and returns MCP envelopes", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        tool: "paper_search",
        data: { results: [{ chunk_id: "c1", text: "evidence" }] },
      }),
    });
    const client = createWorkbenchClient({
      baseUrl: "http://127.0.0.1:3091",
      fetchImpl: fetchImpl as never,
    });

    const result = await client.search({ query: "reflection", top_k: 3 });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:3091/api/search",
      expect.objectContaining({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query: "reflection", top_k: 3 }),
      }),
    );
    expect(result.data?.results[0].chunk_id).toBe("c1");
  });
});
```

- [ ] **Step 4: Run frontend tests to verify they fail**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench install
pnpm --dir integrations/paper-rag-workbench test
```

Expected: FAIL because `src/api/client.ts` does not exist.

- [ ] **Step 5: Create shared TypeScript types**

Create `integrations/paper-rag-workbench/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

Create `integrations/paper-rag-workbench/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Create `integrations/paper-rag-workbench/src/types.ts`:

```ts
export type McpEnvelope<TData = Record<string, unknown>> = {
  ok: boolean;
  tool: string;
  trace_id?: string | null;
  evidence_role?: string;
  warnings?: string[];
  data?: TData;
  error?: {
    code: string;
    message: string;
    retryable?: boolean;
    details?: Record<string, unknown>;
  };
};

export type HealthData = {
  ok: boolean;
  service: string;
  dsh_url: string;
  models: { chat_model: string; small_model: string };
};

export type PaperSummary = {
  paper_id: string;
  title: string;
  arxiv_id?: string | null;
  chunk_count?: number;
  ingested_at?: string;
};

export type EvidenceChunk = {
  chunk_id: string;
  paper_id: string;
  title?: string;
  paper_title?: string;
  page?: number;
  section?: string;
  snippet?: string;
  text?: string;
  score?: number;
};

export type StatusData = {
  sqlite?: { available?: boolean; paper_count?: number; chunk_count?: number };
  llm?: { chat_model?: string; configured?: boolean };
  workbench?: { credentials?: { configured: boolean; source: string | null; writable: boolean } };
  papers?: PaperSummary[];
};

export type PaperListData = { count: number; papers: PaperSummary[] };
export type SearchData = { count: number; results: EvidenceChunk[]; truncated?: boolean };
export type QaData = {
  answer: string;
  citations: string[];
  chunks: EvidenceChunk[];
  abstain?: { decision?: string } | string;
};
export type SectionData = { section?: { name?: string }; section_name?: string; chunks: EvidenceChunk[] };
export type Candidate = {
  id: number;
  title: string;
  source?: string;
  year?: number;
  published_year?: number;
  rank?: number;
  rank_reason?: string;
  reason?: string;
  evidence_role?: string;
};
export type DiscoverData = { run?: { id?: number; topic?: string }; candidates: Candidate[]; count: number };
export type IngestData = { results: Array<{ candidate_id?: number; paper_id?: string; status?: string; n_chunks?: number }>; count?: number };

export type SearchInput = { query: string; top_k?: number; year_min?: number; year_max?: number };
export type QaInput = { question: string; paper_ids?: string[]; resolved_question?: string; top_k?: number };
export type SectionInput = { paper_id: string; section_name: string };
export type DiscoverInput = { topic: string; max_candidates?: number; sources?: string[] };
export type CandidateIngestInput = {
  candidate_ids: number[];
  force?: boolean;
  approval: {
    approved: true;
    operation: "discovery_candidate_ingest";
    candidate_ids: number[];
    destination: "real-library" | "isolated-library";
    side_effects: string[];
  };
};
```

- [ ] **Step 6: Create fixture envelopes**

Create `integrations/paper-rag-workbench/src/api/fixtures.ts`:

```ts
import type { DiscoverData, IngestData, McpEnvelope, PaperListData, QaData, SearchData, SectionData, StatusData } from "../types";

export const statusFixture: McpEnvelope<StatusData> = {
  ok: true,
  tool: "paper_status",
  evidence_role: "metadata",
  warnings: [],
  data: {
    sqlite: { available: true, paper_count: 8, chunk_count: 345 },
    llm: { chat_model: "deepseek-v4-flash", configured: true },
    workbench: { credentials: { configured: true, source: "file", writable: true } },
  },
};

export const papersFixture: McpEnvelope<PaperListData> = {
  ok: true,
  tool: "paper_list",
  evidence_role: "metadata",
  warnings: [],
  data: {
    count: 2,
    papers: [
      { paper_id: "arxiv:2310.11511", title: "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection", arxiv_id: "2310.11511", chunk_count: 58 },
      { paper_id: "arxiv:2005.11401", title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", arxiv_id: "2005.11401", chunk_count: 42 },
    ],
  },
};

export const searchFixture: McpEnvelope<SearchData> = {
  ok: true,
  tool: "paper_search",
  evidence_role: "indexed_chunks",
  warnings: [],
  data: {
    count: 2,
    results: [
      { chunk_id: "chunk-self-rag-1", paper_id: "arxiv:2310.11511", title: "Self-RAG", page: 3, snippet: "SELF-RAG retrieves passages on demand and critiques its own generations.", score: 0.92 },
      { chunk_id: "chunk-self-rag-2", paper_id: "arxiv:2310.11511", title: "Self-RAG", page: 10, snippet: "The model learns to retrieve, generate, and critique through reflection tokens.", score: 0.88 },
    ],
  },
};

export const qaFixture: McpEnvelope<QaData> = {
  ok: true,
  tool: "paper_qa",
  evidence_role: "indexed_chunks",
  trace_id: "trace-workbench-fixture",
  warnings: [],
  data: {
    answer: "Self-RAG trains a model to decide when to retrieve, then critique whether retrieved evidence supports generated claims.",
    citations: ["chunk-self-rag-1", "chunk-self-rag-2"],
    chunks: searchFixture.data!.results,
    abstain: { decision: "answer" },
  },
};

export const sectionFixture: McpEnvelope<SectionData> = {
  ok: true,
  tool: "paper_section",
  evidence_role: "indexed_chunks",
  warnings: [],
  data: {
    section: { name: "Introduction" },
    chunks: searchFixture.data!.results,
  },
};

export const discoverFixture: McpEnvelope<DiscoverData> = {
  ok: true,
  tool: "paper_discover",
  evidence_role: "discovery_only",
  warnings: [],
  data: {
    run: { id: 7, topic: "agentic rag" },
    count: 2,
    candidates: [
      { id: 11, title: "Agentic Retrieval for Language Models", source: "arxiv", year: 2026, rank: 1, rank_reason: "retrieval planning focus", evidence_role: "discovery_only_not_answer_evidence" },
      { id: 12, title: "Evaluating Self-Reflective RAG", source: "arxiv", year: 2025, rank: 2, rank_reason: "evaluation focus", evidence_role: "discovery_only_not_answer_evidence" },
    ],
  },
};

export const ingestFixture: McpEnvelope<IngestData> = {
  ok: true,
  tool: "discovery_candidate_ingest",
  evidence_role: "metadata",
  warnings: [],
  data: {
    count: 1,
    results: [{ candidate_id: 11, paper_id: "arxiv:2601.00001", status: "ingested", n_chunks: 39 }],
  },
};
```

- [ ] **Step 7: Create API client**

Create `integrations/paper-rag-workbench/src/api/client.ts`:

```ts
import {
  discoverFixture,
  ingestFixture,
  papersFixture,
  qaFixture,
  searchFixture,
  sectionFixture,
  statusFixture,
} from "./fixtures";
import type {
  CandidateIngestInput,
  DiscoverData,
  DiscoverInput,
  HealthData,
  IngestData,
  McpEnvelope,
  PaperListData,
  QaData,
  QaInput,
  SearchData,
  SearchInput,
  SectionData,
  SectionInput,
  StatusData,
} from "../types";

type FetchLike = typeof fetch;

export function createWorkbenchClient(options: { baseUrl?: string; fixtureMode?: boolean; fetchImpl?: FetchLike } = {}) {
  const baseUrl = options.baseUrl ?? "";
  const fetchImpl = options.fetchImpl ?? fetch;
  const fixtureMode = options.fixtureMode ?? import.meta.env.VITE_WORKBENCH_FIXTURES === "1";

  const get = async <T>(path: string): Promise<T> => {
    const response = await fetchImpl(`${baseUrl}${path}`);
    if (!response.ok) throw new Error(`GET ${path} failed with ${response.status}`);
    return response.json() as Promise<T>;
  };
  const post = async <T>(path: string, body: unknown): Promise<T> => {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) return response.json() as Promise<T>;
    return response.json() as Promise<T>;
  };

  return {
    health: (): Promise<HealthData> =>
      fixtureMode
        ? Promise.resolve({ ok: true, service: "paper-rag-workbench", dsh_url: "http://127.0.0.1:3080", models: { chat_model: "deepseek-v4-flash", small_model: "deepseek-v4-flash" } })
        : get("/api/health"),
    status: (): Promise<McpEnvelope<StatusData>> => fixtureMode ? Promise.resolve(statusFixture) : get("/api/status"),
    papers: (limit = 20): Promise<McpEnvelope<PaperListData>> => fixtureMode ? Promise.resolve(papersFixture) : get(`/api/papers?limit=${encodeURIComponent(limit)}`),
    search: (input: SearchInput): Promise<McpEnvelope<SearchData>> => fixtureMode ? Promise.resolve(searchFixture) : post("/api/search", input),
    qa: (input: QaInput): Promise<McpEnvelope<QaData>> => fixtureMode ? Promise.resolve(qaFixture) : post("/api/qa", input),
    section: (input: SectionInput): Promise<McpEnvelope<SectionData>> => fixtureMode ? Promise.resolve(sectionFixture) : post("/api/section", input),
    discover: (input: DiscoverInput): Promise<McpEnvelope<DiscoverData>> => fixtureMode ? Promise.resolve(discoverFixture) : post("/api/discover", input),
    ingestCandidates: (input: CandidateIngestInput): Promise<McpEnvelope<IngestData>> => fixtureMode ? Promise.resolve(ingestFixture) : post("/api/ingest/candidates", input),
  };
}

export const workbenchClient = createWorkbenchClient();
```

- [ ] **Step 8: Create minimal app entry and styles**

Create `integrations/paper-rag-workbench/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Paper RAG Workbench</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `integrations/paper-rag-workbench/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

Create `integrations/paper-rag-workbench/src/App.tsx`:

```tsx
export function App() {
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <h1>Paper RAG</h1>
        <nav>
          {["Overview", "Library", "Search", "Ask", "Discover", "DSH Chat"].map((item) => (
            <button key={item} type="button">{item}</button>
          ))}
        </nav>
      </aside>
      <section className="workspace">
        <h2>Paper RAG Workbench</h2>
        <p>Corpus overview loading through fixture mode.</p>
      </section>
    </main>
  );
}
```

Create `integrations/paper-rag-workbench/src/styles.css`:

```css
:root {
  color: #1d2329;
  background: #f6f7f9;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

body {
  margin: 0;
}

button, input, select, textarea {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
}

.sidebar {
  background: #18202a;
  color: #f8fafc;
  padding: 20px 16px;
}

.sidebar h1 {
  font-size: 18px;
  margin: 0 0 24px;
}

.sidebar nav {
  display: grid;
  gap: 6px;
}

.sidebar button {
  border: 0;
  border-radius: 6px;
  color: inherit;
  background: transparent;
  text-align: left;
  padding: 9px 10px;
}

.sidebar button:hover {
  background: rgba(255, 255, 255, 0.1);
}

.workspace {
  padding: 24px;
}
```

- [ ] **Step 9: Run frontend tests and build**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add integrations/paper-rag-workbench
git commit -m "feat: scaffold paper rag workbench frontend"
```

## Task 4: Overview And Library Screens

**Files:**
- Create: `integrations/paper-rag-workbench/src/components/Shell.tsx`
- Create: `integrations/paper-rag-workbench/src/components/StatusBadge.tsx`
- Create: `integrations/paper-rag-workbench/src/components/PaperTable.tsx`
- Create: `integrations/paper-rag-workbench/src/components/EmptyState.tsx`
- Create: `integrations/paper-rag-workbench/src/pages/OverviewPage.tsx`
- Create: `integrations/paper-rag-workbench/src/pages/LibraryPage.tsx`
- Modify: `integrations/paper-rag-workbench/src/App.tsx`
- Modify: `integrations/paper-rag-workbench/src/styles.css`
- Test: `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`
- Test: `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`

**Interfaces:**
- Consumes: `workbenchClient.status()` and `workbenchClient.papers(limit)`
- Produces: `Shell({ active, onNavigate, children })`
- Produces: `OverviewPage({ client })`
- Produces: `LibraryPage({ client })`
- Produces: `PaperTable({ papers, onAsk, onSearch, onSection })`

- [ ] **Step 1: Write failing component and page tests**

Create `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { PaperTable } from "../components/PaperTable";

describe("PaperTable", () => {
  test("renders indexed papers and action buttons", () => {
    render(
      <PaperTable
        papers={[{ paper_id: "arxiv:2310.11511", title: "Self-RAG", arxiv_id: "2310.11511", chunk_count: 58 }]}
        onAsk={vi.fn()}
        onSearch={vi.fn()}
        onSection={vi.fn()}
      />,
    );

    expect(screen.getByText("Self-RAG")).toBeInTheDocument();
    expect(screen.getByText("arxiv:2310.11511")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ask/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /search/i })).toBeInTheDocument();
  });
});
```

Create `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import { OverviewPage } from "../pages/OverviewPage";
import { LibraryPage } from "../pages/LibraryPage";
import { createWorkbenchClient } from "../api/client";

describe("Overview and Library pages", () => {
  test("overview shows corpus health and model status", async () => {
    render(<OverviewPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await waitFor(() => expect(screen.getByText("8")).toBeInTheDocument());
    expect(screen.getByText("345")).toBeInTheDocument();
    expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open dsh chat/i })).toHaveAttribute("href", "http://127.0.0.1:3080");
  });

  test("library filters papers by text", async () => {
    const user = userEvent.setup();
    render(<LibraryPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await waitFor(() => expect(screen.getByText(/Self-RAG/)).toBeInTheDocument());
    await user.type(screen.getByLabelText(/filter papers/i), "2005");

    expect(screen.getByText(/Retrieval-Augmented Generation/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run frontend tests to verify they fail**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test
```

Expected: FAIL because page and component modules are missing.

- [ ] **Step 3: Implement Shell and status components**

Create `Shell.tsx`:

```tsx
import { BookOpen, Compass, Database, MessageSquare, Search, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

const nav = [
  { id: "overview", label: "Overview", icon: Database },
  { id: "library", label: "Library", icon: BookOpen },
  { id: "search", label: "Search", icon: Search },
  { id: "ask", label: "Ask", icon: MessageSquare },
  { id: "discover", label: "Discover", icon: Compass },
  { id: "dsh", label: "DSH Chat", icon: Sparkles },
] as const;

export type RouteId = (typeof nav)[number]["id"];

export function Shell({ active, onNavigate, children }: { active: RouteId; onNavigate: (route: RouteId) => void; children: ReactNode }) {
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <h1>Paper RAG</h1>
        <nav aria-label="Workbench navigation">
          {nav.map(({ id, label, icon: Icon }) => (
            <button key={id} type="button" className={active === id ? "active" : ""} onClick={() => id === "dsh" ? window.open("http://127.0.0.1:3080", "_blank", "noopener,noreferrer") : onNavigate(id)}>
              <Icon size={17} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      </aside>
      <section className="workspace">{children}</section>
    </main>
  );
}
```

Create `StatusBadge.tsx`:

```tsx
export function StatusBadge({ tone, children }: { tone: "good" | "warn" | "neutral"; children: React.ReactNode }) {
  return <span className={`status-badge ${tone}`}>{children}</span>;
}
```

Create `EmptyState.tsx`:

```tsx
export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}
```

- [ ] **Step 4: Implement PaperTable**

Create `PaperTable.tsx`:

```tsx
import type { PaperSummary } from "../types";

export function PaperTable({
  papers,
  onAsk,
  onSearch,
  onSection,
}: {
  papers: PaperSummary[];
  onAsk: (paper: PaperSummary) => void;
  onSearch: (paper: PaperSummary) => void;
  onSection: (paper: PaperSummary) => void;
}) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Title</th>
          <th>Paper ID</th>
          <th>arXiv</th>
          <th>Chunks</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {papers.map((paper) => (
          <tr key={paper.paper_id}>
            <td>{paper.title}</td>
            <td><code>{paper.paper_id}</code></td>
            <td>{paper.arxiv_id || ""}</td>
            <td>{paper.chunk_count ?? 0}</td>
            <td className="row-actions">
              <button type="button" onClick={() => onAsk(paper)}>Ask</button>
              <button type="button" onClick={() => onSearch(paper)}>Search</button>
              <button type="button" onClick={() => onSection(paper)}>Section</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 5: Implement Overview and Library pages**

Create `OverviewPage.tsx` and `LibraryPage.tsx` using `client.status()` and `client.papers(50)`. Each page must render loading text while requests are pending and an `EmptyState` if `ok` is false.

`OverviewPage.tsx` core rendering:

```tsx
<header className="page-header">
  <div>
    <h2>Overview</h2>
    <p>Corpus status, model readiness, and quick actions.</p>
  </div>
  <a className="button-link" href="http://127.0.0.1:3080" target="_blank" rel="noreferrer">Open DSH Chat</a>
</header>
<section className="metric-grid">
  <article><span>Papers</span><strong>{data.sqlite?.paper_count ?? 0}</strong></article>
  <article><span>Chunks</span><strong>{data.sqlite?.chunk_count ?? 0}</strong></article>
  <article><span>Model</span><strong>{data.llm?.chat_model ?? "unknown"}</strong></article>
  <article><span>Credentials</span><StatusBadge tone={data.workbench?.credentials?.configured ? "good" : "warn"}>{data.workbench?.credentials?.configured ? "Configured" : "Missing"}</StatusBadge></article>
</section>
```

`LibraryPage.tsx` must include:

```tsx
<label>
  Filter papers
  <input value={filter} onChange={(event) => setFilter(event.target.value)} />
</label>
<PaperTable papers={filteredPapers} onAsk={...} onSearch={...} onSection={...} />
```

- [ ] **Step 6: Modify App route state**

Modify `App.tsx`:

```tsx
import { useMemo, useState } from "react";
import { createWorkbenchClient } from "./api/client";
import { Shell, type RouteId } from "./components/Shell";
import { LibraryPage } from "./pages/LibraryPage";
import { OverviewPage } from "./pages/OverviewPage";

export function App() {
  const [route, setRoute] = useState<RouteId>("overview");
  const client = useMemo(() => createWorkbenchClient(), []);

  return (
    <Shell active={route} onNavigate={setRoute}>
      {route === "library" ? <LibraryPage client={client} /> : <OverviewPage client={client} />}
    </Shell>
  );
}
```

- [ ] **Step 7: Extend CSS for tables and metrics**

Add classes: `.active`, `.page-header`, `.button-link`, `.metric-grid`, `.data-table`, `.row-actions`, `.status-badge`, `.empty-state`. Use stable sizes and restrained colors; do not add decorative orbs, gradients, or hero sections.

- [ ] **Step 8: Run tests and build**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add integrations/paper-rag-workbench
git commit -m "feat: add workbench overview and library"
```

## Task 5: Evidence Search And Cited QA Screens

**Files:**
- Create: `integrations/paper-rag-workbench/src/components/EvidenceChunkCard.tsx`
- Create: `integrations/paper-rag-workbench/src/components/CitationChips.tsx`
- Create: `integrations/paper-rag-workbench/src/components/AnswerPanel.tsx`
- Create: `integrations/paper-rag-workbench/src/pages/SearchPage.tsx`
- Create: `integrations/paper-rag-workbench/src/pages/AskPage.tsx`
- Modify: `integrations/paper-rag-workbench/src/App.tsx`
- Modify: `integrations/paper-rag-workbench/src/styles.css`
- Modify: `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`
- Modify: `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`

**Interfaces:**
- Consumes: `client.search(input)` and `client.qa(input)`
- Produces: `EvidenceChunkCard({ chunk })`
- Produces: `CitationChips({ citations, onSelect? })`
- Produces: `AnswerPanel({ answer, citations, chunks, abstain })`
- Produces: `SearchPage({ client })`
- Produces: `AskPage({ client })`

- [ ] **Step 1: Add failing tests for evidence and QA**

Append to `components.test.tsx`:

```tsx
import { EvidenceChunkCard } from "../components/EvidenceChunkCard";
import { CitationChips } from "../components/CitationChips";
import { AnswerPanel } from "../components/AnswerPanel";

test("EvidenceChunkCard shows safe chunk metadata", () => {
  render(<EvidenceChunkCard chunk={{ chunk_id: "c1", paper_id: "p1", title: "Paper", page: 3, text: "bounded evidence text" }} />);

  expect(screen.getByText("Paper")).toBeInTheDocument();
  expect(screen.getByText("p1")).toBeInTheDocument();
  expect(screen.getByText("Page 3")).toBeInTheDocument();
  expect(screen.getByText("chunk:c1")).toBeInTheDocument();
});

test("AnswerPanel shows citation chips and evidence", () => {
  render(
    <AnswerPanel
      answer="Self-RAG critiques generations."
      citations={["c1"]}
      chunks={[{ chunk_id: "c1", paper_id: "p1", text: "reflection tokens" }]}
      abstain={{ decision: "answer" }}
    />,
  );

  expect(screen.getByText(/critiques generations/i)).toBeInTheDocument();
  expect(screen.getByText("c1")).toBeInTheDocument();
  expect(screen.getByText(/reflection tokens/i)).toBeInTheDocument();
});
```

Append to `pages.test.tsx`:

```tsx
import userEvent from "@testing-library/user-event";
import { SearchPage } from "../pages/SearchPage";
import { AskPage } from "../pages/AskPage";

test("search page renders evidence chunks", async () => {
  const user = userEvent.setup();
  render(<SearchPage client={createWorkbenchClient({ fixtureMode: true })} />);

  await user.type(screen.getByLabelText(/search evidence/i), "reflection tokens");
  await user.click(screen.getByRole("button", { name: /search/i }));

  expect(await screen.findByText("chunk-self-rag-1")).toBeInTheDocument();
  expect(screen.getByText(/retrieves passages on demand/i)).toBeInTheDocument();
});

test("ask page renders answer citations and DSH prompt bridge", async () => {
  const user = userEvent.setup();
  render(<AskPage client={createWorkbenchClient({ fixtureMode: true })} />);

  await user.type(screen.getByLabelText(/question/i), "What is Self-RAG?");
  await user.click(screen.getByRole("button", { name: /ask/i }));

  expect(await screen.findByText(/decide when to retrieve/i)).toBeInTheDocument();
  expect(screen.getByText("chunk-self-rag-1")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /copy prompt for dsh/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run frontend tests to verify they fail**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test
```

Expected: FAIL because evidence and QA modules are missing.

- [ ] **Step 3: Implement citation and evidence components**

Create `CitationChips.tsx`:

```tsx
export function CitationChips({ citations, onSelect }: { citations: string[]; onSelect?: (citation: string) => void }) {
  if (citations.length === 0) return <span className="muted">No citations</span>;
  return (
    <div className="citation-chips">
      {citations.map((citation) => (
        <button key={citation} type="button" onClick={() => onSelect?.(citation)}>
          {citation}
        </button>
      ))}
    </div>
  );
}
```

Create `EvidenceChunkCard.tsx`:

```tsx
import type { EvidenceChunk } from "../types";

export function EvidenceChunkCard({ chunk }: { chunk: EvidenceChunk }) {
  const title = chunk.title ?? chunk.paper_title ?? chunk.paper_id;
  const text = chunk.text ?? chunk.snippet ?? "";
  return (
    <article className="evidence-card">
      <header>
        <strong>{title}</strong>
        <span>{chunk.paper_id}</span>
        {chunk.page !== undefined ? <span>Page {chunk.page}</span> : null}
      </header>
      <p>{text}</p>
      <footer>
        <code>chunk:{chunk.chunk_id}</code>
        {chunk.score !== undefined ? <span>score {chunk.score.toFixed(2)}</span> : null}
      </footer>
    </article>
  );
}
```

Create `AnswerPanel.tsx`:

```tsx
import type { EvidenceChunk, QaData } from "../types";
import { CitationChips } from "./CitationChips";
import { EvidenceChunkCard } from "./EvidenceChunkCard";
import { StatusBadge } from "./StatusBadge";

export function AnswerPanel({
  answer,
  citations,
  chunks,
  abstain,
}: {
  answer: string;
  citations: string[];
  chunks: EvidenceChunk[];
  abstain: QaData["abstain"];
}) {
  const decision = typeof abstain === "string" ? abstain : abstain?.decision;
  return (
    <section className="answer-panel">
      <header>
        <h3>Answer</h3>
        <StatusBadge tone={decision === "answer" || !decision ? "good" : "warn"}>{decision ?? "answer"}</StatusBadge>
      </header>
      <p>{answer}</p>
      <CitationChips citations={citations} />
      <div className="evidence-list">
        {chunks.map((chunk) => <EvidenceChunkCard key={chunk.chunk_id} chunk={chunk} />)}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Implement SearchPage**

Create `SearchPage.tsx` with local state for query, top-k, loading, envelope, and error. Submit calls `client.search({ query, top_k })`. Disable submit when query is blank. Render `EvidenceChunkCard` for `envelope.data.results`.

- [ ] **Step 5: Implement AskPage**

Create `AskPage.tsx` with local state for question, paper id constraints as comma-separated text, top-k, loading, envelope, and error. Submit calls:

```ts
client.qa({
  question,
  paper_ids: paperIdsText.split(",").map((id) => id.trim()).filter(Boolean),
  top_k,
})
```

Render `AnswerPanel` for successful responses. The "Copy prompt for DSH" button writes this text to the clipboard:

```ts
`基于已入库论文回答：${question}。请给出 Paper RAG 证据引用。`
```

- [ ] **Step 6: Wire routes in App**

Add `search` and `ask` route rendering:

```tsx
{route === "search" ? <SearchPage client={client} /> : null}
{route === "ask" ? <AskPage client={client} /> : null}
```

Keep Overview as the default route.

- [ ] **Step 7: Extend CSS for evidence and forms**

Add stable layout classes: `.form-grid`, `.panel`, `.evidence-list`, `.evidence-card`, `.citation-chips`, `.answer-panel`, `.muted`. Ensure long chunk ids and long titles wrap without overlapping controls.

- [ ] **Step 8: Run tests and build**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add integrations/paper-rag-workbench
git commit -m "feat: add workbench search and ask"
```

## Task 6: Discovery Screen And Approval Dialog

**Files:**
- Create: `integrations/paper-rag-workbench/src/components/CandidateTable.tsx`
- Create: `integrations/paper-rag-workbench/src/components/ApprovalDialog.tsx`
- Create: `integrations/paper-rag-workbench/src/pages/DiscoverPage.tsx`
- Modify: `integrations/paper-rag-workbench/src/App.tsx`
- Modify: `integrations/paper-rag-workbench/src/styles.css`
- Modify: `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`
- Modify: `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`

**Interfaces:**
- Consumes: `client.discover(input)` and `client.ingestCandidates(input)`
- Produces: `CandidateTable({ candidates, selectedIds, onToggle })`
- Produces: `ApprovalDialog({ open, candidateIds, onCancel, onApprove })`
- Produces: `DiscoverPage({ client })`

- [ ] **Step 1: Add failing discovery and approval tests**

Append to `components.test.tsx`:

```tsx
import { CandidateTable } from "../components/CandidateTable";
import { ApprovalDialog } from "../components/ApprovalDialog";

test("CandidateTable labels candidates as non-evidence", () => {
  render(
    <CandidateTable
      candidates={[{ id: 11, title: "Candidate", source: "arxiv", rank: 1, evidence_role: "discovery_only_not_answer_evidence" }]}
      selectedIds={[]}
      onToggle={vi.fn()}
    />,
  );

  expect(screen.getByText("Candidate")).toBeInTheDocument();
  expect(screen.getByText(/not answer evidence/i)).toBeInTheDocument();
});

test("ApprovalDialog names side effects before approval", () => {
  render(<ApprovalDialog open candidateIds={[11]} onCancel={vi.fn()} onApprove={vi.fn()} />);

  expect(screen.getByText(/candidate ids: 11/i)).toBeInTheDocument();
  expect(screen.getByText(/write indexed paper and chunks/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /approve ingest/i })).toBeInTheDocument();
});
```

Append to `pages.test.tsx`:

```tsx
import { DiscoverPage } from "../pages/DiscoverPage";

test("discover requires approval before candidate ingest", async () => {
  const user = userEvent.setup();
  render(<DiscoverPage client={createWorkbenchClient({ fixtureMode: true })} />);

  await user.type(screen.getByLabelText(/topic/i), "agentic rag");
  await user.click(screen.getByRole("button", { name: /discover/i }));
  expect(await screen.findByText(/Agentic Retrieval/)).toBeInTheDocument();

  await user.click(screen.getByLabelText(/select candidate 11/i));
  await user.click(screen.getByRole("button", { name: /ingest selected/i }));
  expect(screen.getByText(/write indexed paper and chunks/i)).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /approve ingest/i }));
  expect(await screen.findByText(/arxiv:2601.00001/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test
```

Expected: FAIL because discovery components and page are missing.

- [ ] **Step 3: Implement CandidateTable**

Create `CandidateTable.tsx`:

```tsx
import type { Candidate } from "../types";

export function CandidateTable({
  candidates,
  selectedIds,
  onToggle,
}: {
  candidates: Candidate[];
  selectedIds: number[];
  onToggle: (id: number) => void;
}) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Select</th>
          <th>Candidate</th>
          <th>Source</th>
          <th>Rank</th>
          <th>Evidence</th>
        </tr>
      </thead>
      <tbody>
        {candidates.map((candidate) => (
          <tr key={candidate.id}>
            <td>
              <input
                aria-label={`Select candidate ${candidate.id}`}
                type="checkbox"
                checked={selectedIds.includes(candidate.id)}
                onChange={() => onToggle(candidate.id)}
              />
            </td>
            <td>
              <strong>{candidate.title}</strong>
              <div className="muted">id {candidate.id}</div>
              <div>{candidate.rank_reason ?? candidate.reason ?? ""}</div>
            </td>
            <td>{candidate.source ?? ""}</td>
            <td>{candidate.rank ?? ""}</td>
            <td>Candidate-only; not answer evidence</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Implement ApprovalDialog**

Create `ApprovalDialog.tsx`:

```tsx
export function ApprovalDialog({
  open,
  candidateIds,
  onCancel,
  onApprove,
}: {
  open: boolean;
  candidateIds: number[];
  onCancel: () => void;
  onApprove: () => void;
}) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-label="Approve candidate ingest">
        <h3>Approve candidate ingest</h3>
        <p>Candidate ids: {candidateIds.join(", ")}</p>
        <ul>
          <li>write indexed paper and chunks</li>
          <li>update the configured Paper RAG corpus</li>
          <li>record ingestion metadata</li>
        </ul>
        <div className="row-actions">
          <button type="button" onClick={onCancel}>Cancel</button>
          <button type="button" className="primary" onClick={onApprove}>Approve ingest</button>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 5: Implement DiscoverPage**

Create `DiscoverPage.tsx` with topic/max-candidate/source controls, result state, selected candidate ids, approval dialog state, and ingest receipt state.

Ingest call must use:

```ts
client.ingestCandidates({
  candidate_ids: selectedIds,
  force: false,
  approval: {
    approved: true,
    operation: "discovery_candidate_ingest",
    candidate_ids: selectedIds,
    destination: "real-library",
    side_effects: [
      "write indexed paper and chunks",
      "update the configured Paper RAG corpus",
      "record ingestion metadata",
    ],
  },
});
```

The `Ingest selected` button is disabled when `selectedIds.length === 0`.

- [ ] **Step 6: Wire Discover route in App**

Render `DiscoverPage` when `route === "discover"`.

- [ ] **Step 7: Extend CSS for modal and candidate table**

Add `.modal-backdrop`, `.modal`, `.primary`, and selection-state styling. Ensure modal content is centered, readable, and does not overflow mobile width.

- [ ] **Step 8: Run tests and build**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add integrations/paper-rag-workbench
git commit -m "feat: add workbench discovery approval"
```

## Task 7: Launcher, README, And Local API Entrypoint

**Files:**
- Create: `src/paper_rag/workbench/__main__.py`
- Create: `scripts/start_workbench.py`
- Create: `integrations/paper-rag-workbench/README.md`
- Modify: `Makefile`
- Modify: `README.md`

**Interfaces:**
- Produces: `python -m paper_rag.workbench --host 127.0.0.1 --port 3091`
- Produces: `scripts/start_workbench.py` launcher for API and Vite dev server.
- Produces: `make workbench` local convenience target.

- [ ] **Step 1: Add failing smoke-style launcher test**

Append to `tests/test_workbench_api.py`:

```python
def test_workbench_module_exports_app_factory():
    import paper_rag.workbench as workbench

    assert callable(workbench.create_app)
    assert workbench.WorkbenchSettings().chat_model == "deepseek-v4-flash"
```

- [ ] **Step 2: Run backend tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_workbench_api.py
```

Expected: PASS because Task 1 exports the app factory.

- [ ] **Step 3: Add Python module entrypoint**

Create `src/paper_rag/workbench/__main__.py`:

```python
from __future__ import annotations

import argparse

import uvicorn

from .api import create_app
from .settings import WorkbenchSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Paper RAG Workbench API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3091)
    args = parser.parse_args()
    uvicorn.run(create_app(WorkbenchSettings.from_env()), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add combined launcher script**

Create `scripts/start_workbench.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
    env.setdefault("CHAT_MODEL", "deepseek-v4-flash")
    env.setdefault("SMALL_MODEL", env["CHAT_MODEL"])
    env.setdefault(
        "PAPER_RAG_DSH_CREDENTIALS_PATH",
        str(repo / "data/runtime/deepseek-harness/credentials/.credentials.yaml"),
    )
    api = subprocess.Popen(
        [sys.executable, "-m", "paper_rag.workbench", "--host", "127.0.0.1", "--port", "3091"],
        cwd=repo,
        env={**env, "PYTHONPATH": str(repo / "src")},
    )
    ui = subprocess.Popen(
        ["pnpm", "--dir", "integrations/paper-rag-workbench", "dev"],
        cwd=repo,
        env=env,
    )
    print("paper rag workbench: http://127.0.0.1:3090", flush=True)
    try:
        return ui.wait()
    finally:
        for proc in (ui, api):
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Add Makefile target**

Modify `Makefile`:

```make
.PHONY: workbench
workbench:
	.venv/bin/python scripts/start_workbench.py
```

- [ ] **Step 6: Add Workbench README**

Create `integrations/paper-rag-workbench/README.md` with:

````markdown
# Paper RAG Workbench

Local visual workbench for the Paper RAG corpus, evidence search, cited QA, and approval-gated discovery ingestion.

## Run

```bash
pnpm --dir integrations/paper-rag-workbench install
.venv/bin/python scripts/start_workbench.py
```

Open `http://127.0.0.1:3090`.

DSH Web remains available at `http://127.0.0.1:3080`.

## Validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_workbench_api.py
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
.venv/bin/python scripts/secret_scan.py
```
````

- [ ] **Step 7: Update root README**

Add a short Workbench section to `README.md`:

````markdown
## Paper RAG Workbench

Run the local visual Workbench:

```bash
.venv/bin/python scripts/start_workbench.py
```

Workbench: `http://127.0.0.1:3090`

DSH Chat: `http://127.0.0.1:3080`
````

- [ ] **Step 8: Run backend tests and frontend build**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_workbench_api.py
pnpm --dir integrations/paper-rag-workbench build
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/paper_rag/workbench scripts/start_workbench.py Makefile README.md integrations/paper-rag-workbench/README.md pyproject.toml
git commit -m "docs: add workbench launcher"
```

## Task 8: Playwright Smoke, DSH Regression, And Final Validation

**Files:**
- Create: `integrations/paper-rag-workbench/tests/workbench.spec.ts`
- Modify: `integrations/paper-rag-workbench/playwright.config.ts`
- Modify: `docs/superpowers/plans/2026-08-14-paper-rag-workbench.md` only to check off executed steps when implementing inline.

**Interfaces:**
- Produces: fixture-mode Playwright smoke that proves the Workbench product workflow without touching the real library.
- Produces: final validation record in the implementation summary.

- [ ] **Step 1: Write Playwright fixture smoke**

Create `integrations/paper-rag-workbench/tests/workbench.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("Workbench fixture workflow covers overview, library, search, ask, and discovery approval", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /overview/i })).toBeVisible();
  await expect(page.getByText("deepseek-v4-flash")).toBeVisible();

  await page.getByRole("button", { name: /library/i }).click();
  await expect(page.getByText(/Self-RAG/)).toBeVisible();

  await page.getByRole("button", { name: /^search$/i }).click();
  await page.getByLabel(/search evidence/i).fill("reflection tokens");
  await page.getByRole("button", { name: /^search$/i }).click();
  await expect(page.getByText("chunk:chunk-self-rag-1")).toBeVisible();

  await page.getByRole("button", { name: /^ask$/i }).click();
  await page.getByLabel(/question/i).fill("What is Self-RAG?");
  await page.getByRole("button", { name: /^ask$/i }).click();
  await expect(page.getByText(/decide when to retrieve/i)).toBeVisible();
  await expect(page.getByText("chunk-self-rag-1")).toBeVisible();

  await page.getByRole("button", { name: /discover/i }).click();
  await page.getByLabel(/topic/i).fill("agentic rag");
  await page.getByRole("button", { name: /discover/i }).click();
  await expect(page.getByText(/Agentic Retrieval/)).toBeVisible();
  await page.getByLabel(/select candidate 11/i).check();
  await page.getByRole("button", { name: /ingest selected/i }).click();
  await expect(page.getByRole("dialog", { name: /approve candidate ingest/i })).toBeVisible();
  await page.getByRole("button", { name: /approve ingest/i }).click();
  await expect(page.getByText("arxiv:2601.00001")).toBeVisible();
});
```

- [ ] **Step 2: Run Playwright smoke**

Run:

```bash
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
```

Expected: PASS. This smoke uses fixture responses and performs no real writes.

- [ ] **Step 3: Run backend regression tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_workbench_api.py tests/test_mcp_frontend_contract.py tests/test_mcp_tools.py tests/test_mcp_security.py
```

Expected: PASS.

- [ ] **Step 4: Run frontend tests and build**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
```

Expected: PASS.

- [ ] **Step 5: Run DSH integration regressions**

Run:

```bash
pnpm --dir integrations/deepseek-harness test
pnpm --dir integrations/deepseek-harness typecheck
pnpm --dir integrations/deepseek-harness smoke
```

Expected: PASS. DSH Web remains independent of the Workbench.

- [ ] **Step 6: Run migration gate tests affected by frontend routing**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_migration_gate.py tests/test_dsh_parity.py
```

Expected: PASS.

- [ ] **Step 7: Run secret scan and DeerFlow runtime check**

Run:

```bash
.venv/bin/python scripts/secret_scan.py
test ! -d integrations/deer-flow
```

Expected: `secret scan: clean`; `integrations/deer-flow` does not exist.

- [ ] **Step 8: Run Workbench live read-only smoke when credentials are available**

Run this only if `data/runtime/deepseek-harness/credentials/.credentials.yaml` exists or `DEEPSEEK_API_KEY`/`OPENAI_API_KEY` is already set:

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from paper_rag.workbench import WorkbenchSettings, create_app

client = TestClient(create_app(WorkbenchSettings.from_env()))
health = client.get("/api/health")
status = client.get("/api/status")
qa = client.post("/api/qa", json={
    "question": "基于已入库论文，Self-RAG 的核心理念是什么？请给证据引用。",
    "paper_ids": ["arxiv:2310.11511"],
    "top_k": 5,
})
print({
    "health": health.status_code,
    "status": status.status_code,
    "qa": qa.status_code,
    "qa_ok": qa.json().get("ok"),
    "citation_count": len((qa.json().get("data") or {}).get("citations") or []),
})
PY
```

Expected: HTTP statuses are `200`; `qa_ok` is `True`; citation count is greater than zero when the local corpus contains `arxiv:2310.11511`. This smoke is read-only.

- [ ] **Step 9: Confirm clean git status**

Run:

```bash
git status --short
```

Expected: no output.

- [ ] **Step 10: Commit Playwright smoke if it was not committed in an earlier task**

```bash
git add integrations/paper-rag-workbench/tests/workbench.spec.ts integrations/paper-rag-workbench/playwright.config.ts
git commit -m "test: add workbench fixture smoke"
```

If those files are already committed with a previous task, skip this commit and record the commit hash that contains the smoke.

---

## Final Acceptance Checklist

- [ ] Workbench starts locally and shows corpus overview as the first screen.
- [ ] Library can be inspected without using a chat box.
- [ ] Search renders bounded evidence chunks with paper, page, and chunk metadata.
- [ ] Ask renders an answer, citation chips, weak/no-evidence states, and expandable evidence.
- [ ] Discover renders candidate-only results and ingests only after explicit approval.
- [ ] Workbench links to DSH Chat at `http://127.0.0.1:3080` without using private DSH session internals.
- [ ] DSH Web and the `Paper Research` preset continue to work.
- [ ] `deepseek-v4-flash` remains configured; no pro model appears in config or UI.
- [ ] `integrations/deer-flow/` is not restored.
- [ ] No `.env`, API keys, runtime credentials, `data/index`, real PDFs, DSH sessions, or temporary smoke data are committed.
- [ ] Python tests, frontend tests, Playwright smoke, DSH integration tests, affected migration tests, secret scan, and git cleanliness pass.

## Plan Self-Review Notes

- Spec coverage: Tasks 1-2 cover the FastAPI adapter, trusted MCP context, credential redaction, and approval model. Tasks 3-6 cover the Workbench screens and DSH bridge. Task 7 covers local launcher and docs. Task 8 covers test, smoke, DSH regression, secret scan, and clean git status.
- Scope check: Compare and Deliverables remain outside the MVP, matching the approved spec.
- Type consistency: Backend `WorkbenchSettings`, `create_app`, and frontend `McpEnvelope`/`WorkbenchClient` names are defined before use and reused consistently.
- Secret boundary: Credential tests assert no secret value is serialized; final validation includes `scripts/secret_scan.py`.
