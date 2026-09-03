# Paper RAG Workspace, Compare, And Scoped Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Paper RAG Workbench Workspace, Compare, and Scoped Notes as three verified gates.

**Architecture:** Add a Workbench-owned SQLite state store under `data/runtime/workbench/state.sqlite`, separate from the Paper RAG corpus database. The Workbench FastAPI adapter owns project, notes, compare, and handoff APIs, while the React app owns the bilingual research cockpit UI. DSH remains an optional prompt handoff target and is never treated as state storage.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, sqlite3, React 18, TypeScript, Vite, Vitest, Testing Library, Playwright, existing Paper RAG MCP/read-store helpers.

## Global Constraints

- Keep `deepseek-v4-flash`; do not switch to Pro models.
- Do not create or restore `integrations/deer-flow/`.
- Do not commit `.env`, API keys, runtime credentials, DSH sessions, real PDFs, Qdrant index files, generated `dist`, `node_modules`, or temporary smoke data.
- Do not run live ingest or any real-library write smoke without explicit user approval.
- Do not depend on DSH private session internals.
- Do not make user notes look like paper evidence.
- Every behavior change should be covered by tests or fixture verification before implementation is considered complete.
- Gate reports must be written to:
  - `docs/reports/workbench-research-workspace-g1.md`
  - `docs/reports/workbench-compare-g2.md`
  - `docs/reports/workbench-scoped-notes-g3.md`

---

## File Structure

- Create `src/paper_rag/workbench/workspace_store.py`: SQLite schema, dataclasses, CRUD methods, compare persistence, DSH prompt composition data.
- Modify `src/paper_rag/workbench/settings.py`: add `workspace_state_path` with env override `PAPER_RAG_WORKBENCH_STATE_PATH`.
- Modify `src/paper_rag/workbench/schemas.py`: add project, evidence pin, note, saved question, compare, and scoped QA request models.
- Modify `src/paper_rag/workbench/api.py`: inject `WorkspaceStore`, add project/compare routes, extend `/api/qa` and `/api/qa/stream` with backward-compatible scoped context.
- Create `tests/test_workbench_workspace_store.py`: store-level tests for Gate 1 and Gate 2 persistence.
- Modify `tests/test_workbench_api.py`: API tests for project routes, compare routes, scoped QA, and no secret leakage.
- Modify `integrations/paper-rag-workbench/src/types.ts`: add project, note, saved question, compare, context policy, and note reference types.
- Modify `integrations/paper-rag-workbench/src/api/client.ts`: add project and compare methods plus scoped QA payload support.
- Modify `integrations/paper-rag-workbench/src/api/fixtures.ts`: add fixture project state, compare run, note refs, and scoped QA data.
- Create `integrations/paper-rag-workbench/src/context/ProjectContext.tsx`: active project state, project refresh helpers, and action methods.
- Modify `integrations/paper-rag-workbench/src/App.tsx`: wrap app in `ProjectProvider` and add `workspace` and `compare` routes.
- Modify `integrations/paper-rag-workbench/src/components/Shell.tsx`: add `Workspace`, `Compare`, and active project switcher UI.
- Create `integrations/paper-rag-workbench/src/components/ProjectSwitcher.tsx`: compact active-project selection and create control.
- Create `integrations/paper-rag-workbench/src/components/PinEvidenceButton.tsx`: idempotent evidence pin button.
- Create `integrations/paper-rag-workbench/src/components/NoteEditor.tsx`: plain text note editor for project, paper, and chunk notes.
- Create `integrations/paper-rag-workbench/src/components/CompareMatrix.tsx`: evidence-first compare table with missing-evidence states.
- Create `integrations/paper-rag-workbench/src/pages/WorkspacePage.tsx`: project cockpit with papers, evidence, notes, saved questions, compare runs, DSH handoff.
- Create `integrations/paper-rag-workbench/src/pages/ComparePage.tsx`: dimension/paper selector and compare matrix.
- Modify `integrations/paper-rag-workbench/src/pages/LibraryPage.tsx`: add paper-to-project actions.
- Modify `integrations/paper-rag-workbench/src/pages/SearchPage.tsx`: add pin evidence and add-paper affordances.
- Modify `integrations/paper-rag-workbench/src/pages/AskPage.tsx`: add save answer, pin evidence, scoped context toggles, and separate note refs.
- Modify `integrations/paper-rag-workbench/src/components/AnswerPanel.tsx`: render note references separately from paper citations.
- Modify `integrations/paper-rag-workbench/src/components/PaperDetailPanel.tsx`: expose add paper, pin chunk, and note actions through optional callbacks.
- Modify `integrations/paper-rag-workbench/src/i18n.tsx`: add Chinese and English copy for Workspace, Compare, pins, notes, saved questions, and context toggles.
- Modify `integrations/paper-rag-workbench/src/__tests__/client.test.ts`: cover new client methods and scoped QA payloads.
- Modify `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`: cover project switcher, pin button, note editor, compare matrix, note refs.
- Modify `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`: cover Gate 1, Gate 2, and Gate 3 page flows.
- Modify `integrations/paper-rag-workbench/tests/workbench.spec.ts`: extend fixture smoke through Workspace, Compare, and Scoped Notes.
- Modify `integrations/paper-rag-workbench/src/styles.css`: responsive workbench layouts, stable buttons, matrices, note areas, and project panels.
- Create gate reports in `docs/reports/`.

---

### Task 1: Gate 1 Backend Workspace Store

**Files:**
- Create: `src/paper_rag/workbench/workspace_store.py`
- Modify: `src/paper_rag/workbench/settings.py`
- Test: `tests/test_workbench_workspace_store.py`

**Interfaces:**
- Produces: `WorkspaceStore(db_path: Path | str)`, `WorkspaceStore.create_project(name: str, description: str = "") -> dict`, `list_projects(include_archived: bool = False) -> list[dict]`, `get_project(project_id: str) -> dict | None`, `update_project(project_id: str, *, name: str | None = None, description: str | None = None) -> dict`, `archive_project(project_id: str) -> dict`, `add_project_paper(project_id: str, paper_id: str, title_snapshot: str = "", source: str = "manual") -> dict`, `pin_evidence(project_id: str, chunk_id: str, paper_id: str, quote_snapshot: str = "", source: str = "manual", score_snapshot: float | None = None, label: str = "", note: str = "") -> dict`, `upsert_note(project_id: str, target_type: str, target_id: str, body: str, note_id: str | None = None) -> dict`, `save_question(project_id: str, question: str, answer: str, citations: list[str], chunk_ids: list[str], trace_id: str | None = None, abstain: object | None = None, context_policy: object | None = None) -> dict`, `build_project_snapshot(project_id: str) -> dict`, `create_dsh_handoff(project_id: str, instruction: str = "") -> dict`.
- Consumes: `WorkbenchSettings.workspace_state_path`.

- [ ] **Step 1: Write failing store tests**

Add these tests to `tests/test_workbench_workspace_store.py`:

```python
from pathlib import Path


def test_workspace_store_creates_updates_archives_project(tmp_path: Path):
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")

    project = store.create_project("Self-RAG 调研", "evidence-first project")
    updated = store.update_project(
        project["project_id"],
        name="Self-RAG 深入调研",
        description="updated",
    )
    archived = store.archive_project(project["project_id"])

    assert project["status"] == "active"
    assert updated["name"] == "Self-RAG 深入调研"
    assert updated["description"] == "updated"
    assert archived["status"] == "archived"
    assert store.list_projects() == []
    assert store.list_projects(include_archived=True)[0]["project_id"] == project["project_id"]


def test_workspace_store_saves_papers_evidence_notes_and_questions(tmp_path: Path):
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("Self-RAG 调研")

    paper = store.add_project_paper(
        project["project_id"],
        "arxiv:2310.11511",
        title_snapshot="Self-RAG",
        source="library",
    )
    duplicate = store.add_project_paper(
        project["project_id"],
        "arxiv:2310.11511",
        title_snapshot="Self-RAG duplicate",
        source="search",
    )
    pin = store.pin_evidence(
        project["project_id"],
        "chunk-self-rag-1",
        "arxiv:2310.11511",
        quote_snapshot="SELF-RAG retrieves passages on demand.",
        source="search",
        score_snapshot=0.92,
        label="method",
    )
    note = store.upsert_note(
        project["project_id"],
        "chunk",
        "chunk-self-rag-1",
        "This is my reading note, not paper evidence.",
    )
    saved = store.save_question(
        project["project_id"],
        "What is Self-RAG?",
        "Self-RAG decides when to retrieve.",
        ["chunk-self-rag-1"],
        ["chunk-self-rag-1"],
        trace_id="trace-workbench-fixture",
        abstain={"decision": "answer"},
    )
    snapshot = store.build_project_snapshot(project["project_id"])

    assert paper["paper_id"] == duplicate["paper_id"]
    assert pin["chunk_id"] == "chunk-self-rag-1"
    assert note["target_type"] == "chunk"
    assert saved["citations"] == ["chunk-self-rag-1"]
    assert snapshot["summary"] == {
        "paper_count": 1,
        "evidence_count": 1,
        "note_count": 1,
        "saved_question_count": 1,
        "compare_run_count": 0,
    }


def test_workspace_store_dsh_handoff_prompt_is_secret_safe(tmp_path: Path):
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("Self-RAG 调研", "project description")
    store.add_project_paper(project["project_id"], "arxiv:2310.11511", "Self-RAG", "library")
    store.pin_evidence(
        project["project_id"],
        "chunk-self-rag-1",
        "arxiv:2310.11511",
        quote_snapshot="evidence excerpt",
        source="ask",
    )
    store.upsert_note(project["project_id"], "project", project["project_id"], "local note")

    handoff = store.create_dsh_handoff(project["project_id"], "Compare methods.")

    assert "Self-RAG 调研" in handoff["prompt"]
    assert "chunk-self-rag-1" in handoff["prompt"]
    assert "local note" in handoff["prompt"]
    assert "sk-" not in handoff["prompt"]
    assert ".credentials" not in handoff["prompt"]
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_workbench_workspace_store.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'paper_rag.workbench.workspace_store'`.

- [ ] **Step 3: Implement minimal store and settings**

Create `workspace_store.py` using `sqlite3`, parameterized SQL, JSON helpers, `uuid.uuid4().hex`, and UTC ISO timestamps. Add `workspace_state_path: Path | None = None` to `WorkbenchSettings`, load `PAPER_RAG_WORKBENCH_STATE_PATH`, and default to `Path("data/runtime/workbench/state.sqlite")` inside `create_app` when unset.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_workbench_workspace_store.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paper_rag/workbench/workspace_store.py src/paper_rag/workbench/settings.py tests/test_workbench_workspace_store.py
git commit -m "feat: add workbench workspace store"
```

---

### Task 2: Gate 1 Project API

**Files:**
- Modify: `src/paper_rag/workbench/schemas.py`
- Modify: `src/paper_rag/workbench/api.py`
- Test: `tests/test_workbench_api.py`

**Interfaces:**
- Consumes: `WorkspaceStore` methods from Task 1.
- Produces: `GET/POST/PATCH /api/projects`, paper/evidence/note/question/handoff project endpoints.

- [ ] **Step 1: Write failing API tests**

Add tests to `tests/test_workbench_api.py`:

```python
def test_project_api_creates_project_and_saves_research_objects(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")
    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *_args: {},
            workspace_store=store,
        )
    )

    created = client.post(
        "/api/projects",
        json={"name": "Self-RAG 调研", "description": "project"},
    ).json()
    project_id = created["project"]["project_id"]

    paper = client.post(
        f"/api/projects/{project_id}/papers",
        json={
            "paper_id": "arxiv:2310.11511",
            "title_snapshot": "Self-RAG",
            "source": "library",
        },
    ).json()
    evidence = client.post(
        f"/api/projects/{project_id}/evidence",
        json={
            "chunk_id": "chunk-self-rag-1",
            "paper_id": "arxiv:2310.11511",
            "quote_snapshot": "SELF-RAG retrieves passages on demand.",
            "source": "search",
        },
    ).json()
    note = client.post(
        f"/api/projects/{project_id}/notes",
        json={
            "target_type": "chunk",
            "target_id": "chunk-self-rag-1",
            "body": "local interpretation",
        },
    ).json()
    saved = client.post(
        f"/api/projects/{project_id}/questions",
        json={
            "question": "What is Self-RAG?",
            "answer": "It retrieves and critiques.",
            "citations": ["chunk-self-rag-1"],
            "chunk_ids": ["chunk-self-rag-1"],
            "trace_id": "trace-workbench-fixture",
            "abstain": {"decision": "answer"},
        },
    ).json()
    detail = client.get(f"/api/projects/{project_id}").json()

    assert created["project"]["name"] == "Self-RAG 调研"
    assert paper["paper"]["paper_id"] == "arxiv:2310.11511"
    assert evidence["evidence"]["chunk_id"] == "chunk-self-rag-1"
    assert note["note"]["body"] == "local interpretation"
    assert saved["question"]["citations"] == ["chunk-self-rag-1"]
    assert detail["summary"]["paper_count"] == 1
    assert detail["summary"]["evidence_count"] == 1
    assert "sk-" not in str(detail)


def test_project_api_archives_and_excludes_archived_projects(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *_args: {},
            workspace_store=WorkspaceStore(tmp_path / "state.sqlite"),
        )
    )

    project_id = client.post("/api/projects", json={"name": "Archive me"}).json()["project"][
        "project_id"
    ]
    archived = client.post(f"/api/projects/{project_id}/archive").json()
    active_list = client.get("/api/projects").json()
    full_list = client.get("/api/projects?include_archived=true").json()

    assert archived["project"]["status"] == "archived"
    assert active_list["projects"] == []
    assert full_list["projects"][0]["project_id"] == project_id


def test_project_dsh_handoff_uses_project_context_without_calling_tools(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    calls = []
    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("Self-RAG 调研")
    store.add_project_paper(project["project_id"], "arxiv:2310.11511", "Self-RAG", "library")
    store.pin_evidence(
        project["project_id"],
        "chunk-self-rag-1",
        "arxiv:2310.11511",
        "evidence excerpt",
        "ask",
    )
    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *args: calls.append(args),
            workspace_store=store,
        )
    )

    response = client.post(
        f"/api/projects/{project['project_id']}/dsh-handoff",
        json={"instruction": "Compare methods."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dsh_url"] == "http://127.0.0.1:3080"
    assert "Compare methods." in payload["prompt"]
    assert "chunk-self-rag-1" in payload["prompt"]
    assert calls == []
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_workbench_api.py -k "project_api or project_dsh" -q`

Expected: FAIL with FastAPI route/schema errors because project endpoints are missing.

- [ ] **Step 3: Implement schemas and routes**

Add strict Pydantic models: `ProjectCreateRequest`, `ProjectUpdateRequest`, `ProjectPaperRequest`, `EvidencePinRequest`, `NoteRequest`, `SavedQuestionRequest`, `ProjectHandoffRequest`. Update `create_app(..., workspace_store: WorkspaceStore | None = None)` and add endpoints returning dictionaries with keys `project`, `projects`, `paper`, `evidence`, `note`, `question`, `summary`, and `dsh_url/prompt`.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_workbench_api.py -k "project_api or project_dsh" -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paper_rag/workbench/schemas.py src/paper_rag/workbench/api.py tests/test_workbench_api.py
git commit -m "feat: expose workbench project api"
```

---

### Task 3: Gate 1 Frontend Client, Types, Fixtures, And Project Context

**Files:**
- Modify: `integrations/paper-rag-workbench/src/types.ts`
- Modify: `integrations/paper-rag-workbench/src/api/client.ts`
- Modify: `integrations/paper-rag-workbench/src/api/fixtures.ts`
- Create: `integrations/paper-rag-workbench/src/context/ProjectContext.tsx`
- Modify: `integrations/paper-rag-workbench/src/__tests__/client.test.ts`
- Modify: `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`

**Interfaces:**
- Produces: typed `ProjectSummary`, `ProjectDetail`, `EvidencePin`, `ResearchNote`, `SavedQuestion`, `CompareRun`, `ContextPolicy`, and `useProjectContext()`.
- Consumes: Gate 1 project API from Task 2.

- [ ] **Step 1: Write failing frontend tests**

Add client tests that call `client.createProject`, `client.addProjectPaper`, `client.pinEvidence`, `client.createNote`, `client.saveQuestion`, and `client.projectDshHandoff` in fixture mode. Add a component/context test that renders `ProjectProvider`, loads fixture projects, creates a new project, and exposes `activeProject`.

- [ ] **Step 2: Verify RED**

Run: `pnpm --dir integrations/paper-rag-workbench test -- client.test.ts components.test.tsx`

Expected: FAIL with TypeScript errors for missing client methods and `ProjectProvider`.

- [ ] **Step 3: Implement types, fixture data, client methods, and context**

Add fixture project data using the existing Self-RAG fixture chunks. Implement fixture-mode methods with in-memory arrays scoped to the client instance so tests can create and mutate projects without a backend. Implement `ProjectProvider` with `projects`, `activeProject`, `activeProjectId`, `setActiveProjectId`, `refreshProjects`, `createProject`, `addPaper`, `pinEvidence`, `createNote`, `saveQuestion`, and `projectDshHandoff`.

- [ ] **Step 4: Verify GREEN**

Run: `pnpm --dir integrations/paper-rag-workbench test -- client.test.ts components.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add integrations/paper-rag-workbench/src/types.ts integrations/paper-rag-workbench/src/api/client.ts integrations/paper-rag-workbench/src/api/fixtures.ts integrations/paper-rag-workbench/src/context/ProjectContext.tsx integrations/paper-rag-workbench/src/__tests__/client.test.ts integrations/paper-rag-workbench/src/__tests__/components.test.tsx
git commit -m "feat: add workbench project client context"
```

---

### Task 4: Gate 1 Workspace UI And Cross-Page Actions

**Files:**
- Modify: `integrations/paper-rag-workbench/src/App.tsx`
- Modify: `integrations/paper-rag-workbench/src/components/Shell.tsx`
- Create: `integrations/paper-rag-workbench/src/components/ProjectSwitcher.tsx`
- Create: `integrations/paper-rag-workbench/src/components/PinEvidenceButton.tsx`
- Create: `integrations/paper-rag-workbench/src/components/NoteEditor.tsx`
- Create: `integrations/paper-rag-workbench/src/pages/WorkspacePage.tsx`
- Modify: `integrations/paper-rag-workbench/src/pages/LibraryPage.tsx`
- Modify: `integrations/paper-rag-workbench/src/pages/SearchPage.tsx`
- Modify: `integrations/paper-rag-workbench/src/pages/AskPage.tsx`
- Modify: `integrations/paper-rag-workbench/src/components/PaperTable.tsx`
- Modify: `integrations/paper-rag-workbench/src/components/PaperDetailPanel.tsx`
- Modify: `integrations/paper-rag-workbench/src/components/EvidenceChunkCard.tsx`
- Modify: `integrations/paper-rag-workbench/src/i18n.tsx`
- Modify: `integrations/paper-rag-workbench/src/styles.css`
- Modify: `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`
- Modify: `integrations/paper-rag-workbench/tests/workbench.spec.ts`

**Interfaces:**
- Consumes: `ProjectProvider` from Task 3.
- Produces: Workspace route, active project switcher, add paper, pin evidence, note creation, save answer, project handoff.

- [ ] **Step 1: Write failing page and Playwright fixture tests**

Add tests that:

- render `App` in fixture mode and assert `工作区` navigation exists,
- create a project from Workspace empty state,
- add the Self-RAG paper from Library to the active project,
- pin `chunk-self-rag-1` from Search,
- ask a question, save the answer, and pin a citation,
- create a chunk note,
- generate a project DSH handoff prompt,
- verify the Playwright fixture smoke performs the same flow.

- [ ] **Step 2: Verify RED**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- pages.test.tsx
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
```

Expected: FAIL because Workspace route/actions do not exist.

- [ ] **Step 3: Implement Workspace UI**

Wrap `Shell` children with `ProjectProvider`. Add `workspace` to `RouteId` and nav. Implement accessible buttons and stable labels:

- Chinese: `工作区`, `创建项目`, `加入项目`, `已在项目中`, `钉选证据`, `已钉选`, `保存问答`, `添加笔记`, `发送项目到 DSH`.
- English equivalents in i18n.

Keep cards shallow, use existing panel/table/evidence-card styles, and avoid nesting cards inside cards.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- pages.test.tsx components.test.tsx
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add integrations/paper-rag-workbench/src/App.tsx integrations/paper-rag-workbench/src/components integrations/paper-rag-workbench/src/pages integrations/paper-rag-workbench/src/i18n.tsx integrations/paper-rag-workbench/src/styles.css integrations/paper-rag-workbench/src/__tests__/pages.test.tsx integrations/paper-rag-workbench/tests/workbench.spec.ts
git commit -m "feat: add research workspace ui"
```

---

### Task 5: Gate 1 Verification And Report

**Files:**
- Create: `docs/reports/workbench-research-workspace-g1.md`

**Interfaces:**
- Consumes: Gate 1 implementation.
- Produces: Gate 1 go/no-go report.

- [ ] **Step 1: Run Gate 1 verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_workbench_workspace_store.py tests/test_workbench_api.py -q
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
.venv/bin/python scripts/secret_scan.py
git status --short --branch
```

- [ ] **Step 2: Write report**

Write `docs/reports/workbench-research-workspace-g1.md` with:

```markdown
# Workbench Research Workspace G1 Report

## Status

Go.

## Implementation Summary

- Added Workbench local workspace state database.
- Added project, paper, evidence pin, note, saved question, and project DSH handoff APIs.
- Added Workspace UI, active project switcher, cross-page save/pin actions, and bilingual copy.

## Verification

- `.venv/bin/python -m pytest tests/test_workbench_workspace_store.py tests/test_workbench_api.py -q`: PASS
- `pnpm --dir integrations/paper-rag-workbench test`: PASS
- `pnpm --dir integrations/paper-rag-workbench build`: PASS
- `VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright`: PASS
- `.venv/bin/python scripts/secret_scan.py`: PASS
- `git status --short --branch`: clean after commit

## Degraded Modes

- DSH unavailable does not block project storage or Workspace use.
- Missing corpus references remain visible through stored snapshots.

## Next Gate

Gate 2 Compare V1 is ready.
```

- [ ] **Step 3: Commit**

```bash
git add docs/reports/workbench-research-workspace-g1.md
git commit -m "docs: add workspace gate 1 report"
```

---

### Task 6: Gate 2 Backend Compare Store And API

**Files:**
- Modify: `src/paper_rag/workbench/workspace_store.py`
- Modify: `src/paper_rag/workbench/schemas.py`
- Modify: `src/paper_rag/workbench/api.py`
- Modify: `tests/test_workbench_workspace_store.py`
- Modify: `tests/test_workbench_api.py`

**Interfaces:**
- Consumes: Gate 1 project papers, evidence pins, notes, and saved questions.
- Produces: `create_compare_run(project_id: str, paper_ids: list[str], dimensions: list[str]) -> dict`, `list_compare_runs(project_id: str) -> list[dict]`, `get_compare_run(project_id: str, run_id: str) -> dict | None`, compare API routes.

- [ ] **Step 1: Write failing compare tests**

Add tests proving:

- compare cells are created for every selected paper/dimension,
- cells with pinned evidence expose `evidence_chunk_ids` and `confidence == "evidence_backed"`,
- cells without pinned evidence say `No pinned evidence` and `confidence == "missing"`,
- compare run persists and can be listed,
- compare handoff prompt includes dimensions and evidence ids,
- no LLM or DSH call is required.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_workbench_workspace_store.py tests/test_workbench_api.py -k compare -q
```

Expected: FAIL because compare storage and routes are missing.

- [ ] **Step 3: Implement evidence-only compare**

Extend schema with `compare_runs` and `compare_cells`. Implement deterministic evidence-only summaries:

- if paper has pinned chunks: `Evidence pinned for {dimension}: {first_quote}`
- if no pinned chunks: `No pinned evidence`

Set run `status` to `degraded` and warning `LLM synthesis unavailable; rendered evidence-only matrix.` unless a future service is added. This satisfies the degraded fallback without adding a new LLM dependency.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_workbench_workspace_store.py tests/test_workbench_api.py -k compare -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paper_rag/workbench/workspace_store.py src/paper_rag/workbench/schemas.py src/paper_rag/workbench/api.py tests/test_workbench_workspace_store.py tests/test_workbench_api.py
git commit -m "feat: add evidence-first compare api"
```

---

### Task 7: Gate 2 Compare UI

**Files:**
- Modify: `integrations/paper-rag-workbench/src/types.ts`
- Modify: `integrations/paper-rag-workbench/src/api/client.ts`
- Modify: `integrations/paper-rag-workbench/src/api/fixtures.ts`
- Modify: `integrations/paper-rag-workbench/src/App.tsx`
- Modify: `integrations/paper-rag-workbench/src/components/Shell.tsx`
- Create: `integrations/paper-rag-workbench/src/components/CompareMatrix.tsx`
- Create: `integrations/paper-rag-workbench/src/pages/ComparePage.tsx`
- Modify: `integrations/paper-rag-workbench/src/pages/WorkspacePage.tsx`
- Modify: `integrations/paper-rag-workbench/src/i18n.tsx`
- Modify: `integrations/paper-rag-workbench/src/styles.css`
- Modify: `integrations/paper-rag-workbench/src/__tests__/client.test.ts`
- Modify: `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`
- Modify: `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`
- Modify: `integrations/paper-rag-workbench/tests/workbench.spec.ts`

**Interfaces:**
- Consumes: compare API from Task 6.
- Produces: Compare route, dimension selector, paper subset selector, matrix, saved compare runs panel, DSH handoff preview.

- [ ] **Step 1: Write failing compare UI tests**

Add tests that create/select a fixture project, navigate to `对比`, choose dimensions `method` and `limitation`, run compare, assert `chunk-self-rag-1` appears in a matrix cell, assert `No pinned evidence` appears for missing evidence, save/list run, and open DSH prompt preview.

- [ ] **Step 2: Verify RED**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- client.test.ts components.test.tsx pages.test.tsx
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
```

Expected: FAIL because Compare UI and client methods are missing.

- [ ] **Step 3: Implement Compare UI**

Add `nav.compare`, `compare.title`, `compare.run`, `compare.dimensions`, `compare.noPinnedEvidence`, `compare.evidence`, `compare.confidence`, `compare.sendToDsh`, and equivalent Chinese copy. Implement the matrix as a normal table with stable column widths and buttons for evidence chunk ids.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- client.test.ts components.test.tsx pages.test.tsx
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add integrations/paper-rag-workbench/src integrations/paper-rag-workbench/tests/workbench.spec.ts
git commit -m "feat: add workbench compare ui"
```

---

### Task 8: Gate 2 Verification And Report

**Files:**
- Create: `docs/reports/workbench-compare-g2.md`

**Interfaces:**
- Consumes: Gate 2 implementation.
- Produces: Gate 2 go/no-go report.

- [ ] **Step 1: Run Gate 2 verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_workbench_workspace_store.py tests/test_workbench_api.py -q
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
.venv/bin/python scripts/secret_scan.py
git status --short --branch
```

- [ ] **Step 2: Write report**

Write `docs/reports/workbench-compare-g2.md` with status `Go`, verification command results, evidence-only degraded mode, and `Gate 3 Scoped Notes Retrieval V1 is ready.`

- [ ] **Step 3: Commit**

```bash
git add docs/reports/workbench-compare-g2.md
git commit -m "docs: add compare gate 2 report"
```

---

### Task 9: Gate 3 Backend Scoped Notes QA

**Files:**
- Modify: `src/paper_rag/workbench/schemas.py`
- Modify: `src/paper_rag/workbench/api.py`
- Modify: `src/paper_rag/workbench/workspace_store.py`
- Modify: `tests/test_workbench_api.py`
- Modify: `tests/test_workbench_workspace_store.py`

**Interfaces:**
- Consumes: project snapshot from Gate 1.
- Produces: backward-compatible `QaRequest` fields `project_id` and `context_policy`, `QaData` enrichment with `note_refs`, `context_policy`, and `project_context_warnings`.

- [ ] **Step 1: Write failing scoped QA tests**

Add tests proving:

- `/api/qa` without project context sends exactly the previous `paper_qa` args.
- `/api/qa` with context policy adds project paper ids when `restrict_to_project_papers` is true.
- `/api/qa` with notes enabled returns `note_refs` separately and does not place note ids in `citations`.
- `/api/qa/stream` forwards restricted paper ids and includes policy fields in final event data.
- saved questions can store the context policy.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_workbench_api.py tests/test_workbench_workspace_store.py -k "qa or context_policy or scoped" -q
```

Expected: FAIL because scoped QA fields are forbidden or ignored.

- [ ] **Step 3: Implement scoped context enrichment**

Extend `QaRequest` with:

```python
class ContextPolicy(StrictRequest):
    include_pinned_evidence: bool = False
    include_notes: bool = False
    restrict_to_project_papers: bool = False
```

Build internal QA args by preserving current args when no project context is provided. When restricted, union the request paper ids with project paper ids and pass them as `paper_ids`. After the MCP call returns, add `note_refs`, `context_policy`, and `project_context_warnings` under `data` without changing `citations`. For stream final events, enrich `done` data with the same fields.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_workbench_api.py tests/test_workbench_workspace_store.py -k "qa or context_policy or scoped" -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paper_rag/workbench/schemas.py src/paper_rag/workbench/api.py src/paper_rag/workbench/workspace_store.py tests/test_workbench_api.py tests/test_workbench_workspace_store.py
git commit -m "feat: add scoped project qa context"
```

---

### Task 10: Gate 3 Ask UI Scoped Context

**Files:**
- Modify: `integrations/paper-rag-workbench/src/types.ts`
- Modify: `integrations/paper-rag-workbench/src/api/client.ts`
- Modify: `integrations/paper-rag-workbench/src/api/fixtures.ts`
- Modify: `integrations/paper-rag-workbench/src/pages/AskPage.tsx`
- Modify: `integrations/paper-rag-workbench/src/components/AnswerPanel.tsx`
- Modify: `integrations/paper-rag-workbench/src/i18n.tsx`
- Modify: `integrations/paper-rag-workbench/src/styles.css`
- Modify: `integrations/paper-rag-workbench/src/__tests__/client.test.ts`
- Modify: `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`
- Modify: `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`
- Modify: `integrations/paper-rag-workbench/tests/workbench.spec.ts`

**Interfaces:**
- Consumes: scoped QA backend from Task 9 and `ProjectProvider`.
- Produces: Ask context controls and separate note reference rendering.

- [ ] **Step 1: Write failing scoped Ask UI tests**

Add tests that:

- render Ask with no context and assert current QA payload has no `project_id`,
- enable `include pinned evidence`, `include notes`, and `restrict to project papers`,
- assert `client.qaStream` receives `project_id` and `context_policy`,
- assert answer renders paper citations under citations and notes under `用户笔记引用`,
- save scoped answer and assert saved question records the context policy.

- [ ] **Step 2: Verify RED**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- client.test.ts components.test.tsx pages.test.tsx
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
```

Expected: FAIL because Ask context controls and note refs are missing.

- [ ] **Step 3: Implement scoped Ask UI**

Add a compact context panel below Ask form with toggles. Default all toggles off so global corpus QA remains unchanged. Pass `project_id` only when at least one context toggle is enabled. Render note refs through a separate component section labelled `用户笔记引用` / `User note references`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- client.test.ts components.test.tsx pages.test.tsx
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add integrations/paper-rag-workbench/src integrations/paper-rag-workbench/tests/workbench.spec.ts
git commit -m "feat: add scoped notes ask controls"
```

---

### Task 11: Gate 3 Verification, Final Reports, And Goal Audit

**Files:**
- Create: `docs/reports/workbench-scoped-notes-g3.md`

**Interfaces:**
- Consumes: Gate 1, Gate 2, and Gate 3 implementation.
- Produces: final go/no-go evidence for the active goal.

- [ ] **Step 1: Run final verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_workbench_workspace_store.py tests/test_workbench_api.py -q
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
.venv/bin/python scripts/secret_scan.py
git status --short --branch
```

If local services and credentials are available, run a read-only live smoke that asks a project-scoped question without ingesting, reindexing, rebuilding, deleting, or mutating the real corpus. If unavailable, record the reason as skipped in the Gate 3 report rather than marking the goal blocked.

- [ ] **Step 2: Write Gate 3 report**

Write `docs/reports/workbench-scoped-notes-g3.md` with status `Go`, command outputs, scoped QA summary, live read-only smoke status, no-go risks if any, and deferred work.

- [ ] **Step 3: Commit report**

```bash
git add docs/reports/workbench-scoped-notes-g3.md
git commit -m "docs: add scoped notes gate 3 report"
```

- [ ] **Step 4: Completion audit**

Check:

```bash
git log --oneline -12
git status --short --branch
rg -n "deepseek-v4-flash|Pro|integrations/deer-flow|No pinned evidence|用户笔记引用|note_refs|context_policy" src integrations/paper-rag-workbench docs/reports
```

Confirm:

- reports exist and show `Go`,
- all verification commands pass,
- no tracked secret/runtime/index/PDF/build files are present,
- Workbench is still Chinese-first with English toggle,
- global QA unchanged without project context,
- note refs and paper citations are separate,
- DSH handoff is prompt-only and optional.

- [ ] **Step 5: Final commit if audit caused doc/test updates**

If any audit updates were made, commit them. Otherwise leave the tree clean.
