# Paper RAG Research Workspace V1 Design

## Purpose

Turn Paper RAG Workbench from a useful corpus browser into a persistent local
research workspace. The release adds a project context layer so papers, evidence
chunks, notes, saved questions, and DSH handoffs can be organized around a
research topic instead of living only inside one page or one chat turn.

This release keeps Workbench as the primary UI and DSH as the deep-task
companion. Workbench owns inspectable local research state. DSH receives a
prepared context package when the user wants long-form analysis, comparison, or
drafting.

## Current Context

The current Workbench runs at `http://127.0.0.1:3090` and already exposes:

- Overview: corpus, model, credentials, and DSH entry.
- Health: SQLite, Qdrant, LLM, retrieval fallback, and quality diagnostics.
- Library: indexed papers, section reading, paper detail, and DSH handoff.
- Search: evidence retrieval and chunk inspection.
- Ask: streaming QA, citations, chunk drilldown, and agent timeline.
- Discover: candidate discovery and approval-gated ingest.
- Bilingual UI: Chinese default with English toggle.

The strongest product gap is that useful objects do not persist as a research
unit. A user can find a paper, inspect a chunk, ask a question, and copy a DSH
handoff prompt, but the system does not yet remember that these belong to the
same research topic.

## Goals

- Add a first-class `Workspace` navigation area. In the API and data model,
  individual research topics are called projects.
- Let users create, select, rename, and archive local research projects.
- Let Library, Search, Ask, and Paper Detail add papers to the active project.
- Let Search, Ask citations, and Paper Detail pin evidence chunks to the active
  project.
- Let users create notes on a project, paper, or evidence chunk.
- Let users save QA results to a project, including the question, answer,
  citations, chunk ids, abstain state, and trace id when available.
- Let users generate a DSH handoff prompt from the selected project context.
- Keep all project state local and secret-safe.
- Preserve the existing approval boundary for every real corpus write.
- Preserve `deepseek-v4-flash` as the configured model.
- Keep DSH optional for the core Workbench experience.

## Non-Goals

- Do not implement Compare, Literature Review, Related Work, Annotated
  Bibliography, Evidence Pack export, Markdown export, BibTeX export, or PDF
  export in this release.
- Do not add multi-user auth, cloud sync, billing, sharing, or collaboration.
- Do not store API keys, credential files, raw DSH sessions, real PDFs, Qdrant
  index files, or generated answer caches in git.
- Do not depend on DSH private session internals or embed DSH Web inside the
  Workbench.
- Do not reintroduce DeerFlow routes, DeerFlow frontend code, or
  `integrations/deer-flow/`.
- Do not run automated live ingest or other real-library write smoke tests
  without explicit user approval.
- Do not change Paper RAG retrieval, ingestion, parsing, or ranking behavior
  except where tests need read-only project context plumbing.

## Recommended Approach

Add a Workbench-owned local state database separate from the Paper RAG corpus
database:

```text
data/runtime/workbench/state.sqlite
```

The corpus database remains the source of truth for papers and chunks. The new
state database stores only user workspace metadata and references to corpus
objects:

```text
Workbench SPA
  -> Workbench FastAPI adapter
     -> paper_rag.workbench.workspace_store
        -> data/runtime/workbench/state.sqlite
     -> existing Paper RAG MCP registry for corpus reads
     -> existing DSH handoff endpoint for prompt preparation
```

This keeps project state durable without coupling it to DSH sessions or corpus
index internals. If the corpus is rebuilt, projects still retain paper ids and
chunk ids, and the UI can mark missing references as unavailable rather than
silently deleting research history.

## Data Model

### `projects`

- `project_id`: stable local id.
- `name`: user-visible title.
- `description`: optional short summary.
- `status`: `active` or `archived`.
- `created_at`, `updated_at`.

### `project_papers`

- `project_id`.
- `paper_id`.
- `title_snapshot`: title at time of adding, used as fallback if corpus lookup
  later fails.
- `source`: `library`, `search`, `ask`, `paper_detail`, or `discover`.
- `created_at`.

Unique key: `(project_id, paper_id)`.

### `evidence_pins`

- `pin_id`.
- `project_id`.
- `chunk_id`.
- `paper_id`.
- `label`: optional user label.
- `note`: optional short note directly attached to the pin.
- `source`: `search`, `ask`, `paper_detail`, or `manual`.
- `score_snapshot`: optional retrieval score at pin time.
- `quote_snapshot`: short excerpt or snippet already visible in the UI.
- `created_at`, `updated_at`.

Unique key: `(project_id, chunk_id)`.

### `notes`

- `note_id`.
- `project_id`.
- `target_type`: `project`, `paper`, or `chunk`.
- `target_id`: project id, paper id, or chunk id.
- `body`: Markdown-compatible plain text.
- `created_at`, `updated_at`.

Notes are local user-authored text. They are not automatically injected into
retrieval unless a future spec explicitly adds scoped context retrieval.

### `saved_questions`

- `question_id`.
- `project_id`.
- `question`.
- `answer`.
- `citations_json`: citation tokens returned by QA.
- `chunk_ids_json`: cited and supporting chunk ids.
- `trace_id`: optional Workbench trace id.
- `abstain_json`: optional abstain payload.
- `created_at`.

### `dsh_handoffs`

- `handoff_id`.
- `project_id`.
- `prompt`.
- `paper_ids_json`.
- `chunk_ids_json`.
- `question_ids_json`.
- `created_at`.

This table records prepared handoff prompts, not DSH session content.

## API Design

Add a focused project API under the existing Workbench FastAPI app:

```text
GET    /api/projects
POST   /api/projects
GET    /api/projects/{project_id}
PATCH  /api/projects/{project_id}
POST   /api/projects/{project_id}/archive

POST   /api/projects/{project_id}/papers
DELETE /api/projects/{project_id}/papers/{paper_id}

POST   /api/projects/{project_id}/evidence
PATCH  /api/projects/{project_id}/evidence/{pin_id}
DELETE /api/projects/{project_id}/evidence/{pin_id}

POST   /api/projects/{project_id}/notes
PATCH  /api/projects/{project_id}/notes/{note_id}
DELETE /api/projects/{project_id}/notes/{note_id}

POST   /api/projects/{project_id}/questions
POST   /api/projects/{project_id}/dsh-handoff
```

Read responses should enrich paper and chunk references through existing corpus
read paths when available:

- Paper references include current title, arXiv id, and chunk count if present.
- Evidence pins include current chunk text/page/section if present.
- Missing corpus references remain visible with a warning such as `source item
  unavailable`.

The API should never return filesystem credential paths, raw credential values,
runtime session internals, real PDF paths, or Qdrant index paths.

## UI Design

### Navigation

Add a `Workspace` route near the top of the sidebar. In Chinese UI this is
`工作区`.

The sidebar includes a compact active-project switcher:

```text
当前项目: Self-RAG 调研
```

If no project exists, the switcher shows a create action. If no project is
selected, pin and save actions remain visible but ask the user to create or
select a project.

### Workspace Page

The Workspace page is the project cockpit:

- Project header with name, description, status, and archive action.
- Research summary showing paper count, pinned evidence count, note count, and
  saved question count.
- Papers section with paper cards/table and quick actions: open detail, ask
  about paper, remove from project.
- Evidence section with pinned chunks, page/section metadata, labels, notes,
  and open chunk detail.
- Notes section with project notes and target-linked notes.
- Saved Questions section with question, answer preview, citations, and reopen
  in Ask.
- DSH section with `Send project to DSH`, plus a preview of the prepared prompt.

### Cross-Page Actions

Library:

- `Add to project` on paper rows and Paper Detail.
- If paper is already in the active project, show a saved state.

Search:

- `Pin evidence` on every evidence chunk card.
- `Add paper to project` on result cards when the paper is not saved.

Ask:

- `Save answer to project` once QA completes.
- `Pin evidence` on cited chunks and retrieved supporting chunks.
- `Send answer context to DSH` for ad hoc handoff.

Paper Detail:

- `Add paper to project`.
- `Pin chunk` from the chunk list.
- `Add note` for the paper or selected chunk.

### Notes UX

Notes should be simple and local:

- Plain textarea editor.
- Save, cancel, edit, delete.
- Target badges such as `Project`, `Paper`, or `Chunk`.
- Last updated timestamp.

No rich text editor is needed in V1. Markdown rendering can be added later.

## DSH Integration

DSH receives prepared context, not ownership of project state.

The project handoff prompt should include:

- Project name and description.
- Selected paper ids and titles.
- Pinned evidence chunks with paper id, chunk id, page, section, and excerpt.
- User notes grouped by target.
- Saved questions with citations.
- User-entered task instruction when provided.

The default Chinese prompt should ask DSH to use Paper RAG tools, preserve
citations, and distinguish evidence-backed claims from hypotheses. Example:

```text
基于 Paper RAG Workbench 当前项目继续研究。

项目: Self-RAG 调研
论文: ...
证据: ...
笔记: ...

请使用 Paper RAG 工具核查关键结论，所有论文事实保留证据引用。
```

Workbench may copy the prompt and open DSH Web. If DSH later exposes a stable
public prefill or handoff API, a future spec can replace the copy/open flow.

## Safety And Approval Model

- Creating projects, notes, evidence pins, saved questions, and handoff records
  writes only to `data/runtime/workbench/state.sqlite`.
- These writes do not mutate the Paper RAG corpus, Qdrant index, source PDFs, or
  DSH session store.
- Discover ingest remains approval-gated exactly as today.
- No project action can trigger ingest, reindex, rebuild, delete corpus data, or
  modify credentials.
- Tests must use temporary state databases, not the real runtime state file.
- The runtime state database is not committed.

## Error Handling

- If no active project exists, actions show a small create/select prompt.
- Duplicate paper adds and duplicate evidence pins are idempotent.
- Missing corpus references remain visible with a degraded warning.
- Failed note/project saves show a localized error and keep unsaved text in the
  UI until the user retries or cancels.
- DSH unavailable does not block project use; it only disables or warns on
  handoff.

## Testing Scope

Backend tests:

- Create/list/update/archive project with a temporary SQLite state database.
- Add/remove project papers idempotently.
- Pin/update/remove evidence idempotently.
- Create/update/delete notes for project, paper, and chunk targets.
- Save QA result with citations, chunk ids, abstain state, and trace id.
- Generate project DSH handoff without leaking secrets or local credential
  paths.
- Prove project writes do not touch corpus ingest/reindex paths.

Frontend tests:

- Render project switcher in Chinese and English.
- Create/select project from empty state.
- Add paper from Library fixture into active project.
- Pin evidence from Search and Ask fixture flows.
- Add a note to a pinned chunk.
- Save a QA answer to the active project.
- Generate and display a DSH handoff prompt from project context.

Playwright fixture smoke:

```text
Overview
  -> Workspace empty state
  -> create project
  -> Library add paper
  -> Search pin evidence
  -> Ask save answer and pin citation
  -> Workspace verify paper/evidence/question/note counts
  -> Generate DSH handoff prompt
  -> switch language to English and verify core labels
```

Verification commands:

```text
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
.venv/bin/python scripts/secret_scan.py
git status --short --branch
```

## Acceptance Criteria

- A user can create a local project from the Workbench UI.
- A user can add at least one paper from Library or Paper Detail to the active
  project.
- A user can pin at least one evidence chunk from Search, Ask, or Paper Detail.
- A user can write and edit a note tied to the project, paper, or chunk.
- A user can save a QA result to the active project.
- The Workspace page shows the project papers, evidence, notes, and saved
  questions with citation/chunk drilldown links.
- A user can generate a DSH handoff prompt from the project context.
- DSH handoff does not require DSH private session internals.
- All UI chrome remains bilingual with Chinese default.
- The model remains `deepseek-v4-flash`.
- No DeerFlow code or directory is reintroduced.
- No secrets, runtime credentials, real PDFs, Qdrant index data, generated
  `dist`, `node_modules`, or temporary smoke data are committed.
- All listed verification commands pass.

## Future Specs

- `Compare V1`: use project papers and pinned evidence to build structured
  method/contribution/limitation comparisons.
- `Deliverables V1`: generate literature review, related work, annotated
  bibliography, and evidence pack exports from project context.
- `Scoped Notes Retrieval V1`: optionally include selected project notes as
  question context with explicit user control.
- `DSH Public Handoff API`: replace copy/open prompt handoff if DSH exposes a
  stable public route.
- `Workspace Import/Export`: portable project bundles without PDFs, secrets, or
  index files.
