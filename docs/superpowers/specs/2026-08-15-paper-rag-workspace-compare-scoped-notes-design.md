# Paper RAG Workspace, Compare, And Scoped Notes Gated Design

## Purpose

Implement the next Workbench product arc as one gated program:

- Gate 1: `Research Workspace V1`
- Gate 2: `Compare V1`
- Gate 3: `Scoped Notes Retrieval V1`

The program turns Workbench into a persistent local research environment while
keeping DSH as the optional deep-task companion. Each gate must ship as working,
tested software before the next gate starts.

## Current Context

Paper RAG Workbench already provides the primary UI:

- Overview
- Health
- Library
- Search
- Ask with streaming QA and agent timeline
- Discover with approval-gated ingest
- Paper detail and chunk drilldown components
- DSH handoff prompt preparation
- Chinese-first bilingual UI

The committed V1 spec at
`docs/superpowers/specs/2026-08-15-paper-rag-research-workspace-v1-design.md`
defines the project context layer. This gated design extends that foundation
with structured comparison and scoped use of project notes.

## Product Principle

Workbench owns local, inspectable research state. DSH handles long-form agentic
work when the user explicitly sends context to it.

```text
Workbench
  -> projects
  -> papers
  -> pinned evidence
  -> notes
  -> saved questions
  -> compare matrices
  -> scoped Ask controls

DSH
  -> optional long-running analysis
  -> optional literature review drafting
  -> optional deep comparison prompt execution
```

The Workbench must remain useful if DSH is unavailable.

## Global Constraints

- Keep `deepseek-v4-flash`; do not switch to Pro models.
- Do not create or restore `integrations/deer-flow/`.
- Do not commit `.env`, API keys, runtime credentials, DSH sessions, real PDFs,
  Qdrant index files, generated `dist`, `node_modules`, or temporary smoke data.
- Do not run live ingest or any real-library write smoke without explicit user
  approval.
- Do not depend on DSH private session internals.
- Do not make user notes look like paper evidence.
- Every behavior change should be covered by tests or fixture verification
  before implementation is considered complete.

## Gate Order

### Gate 1: Research Workspace V1

Goal: create a durable project context layer.

Required behavior:

- Create, select, rename, and archive projects.
- Add papers from Library and Paper Detail to the active project.
- Pin evidence chunks from Search, Ask, and Paper Detail.
- Create project, paper, and chunk notes.
- Save QA results with question, answer, citations, chunk ids, abstain state,
  and trace id when available.
- Generate a project-level DSH handoff prompt.

Required storage:

```text
data/runtime/workbench/state.sqlite
```

Required tables:

- `projects`
- `project_papers`
- `evidence_pins`
- `notes`
- `saved_questions`
- `dsh_handoffs`

Completion standard:

- Backend tests use temporary state databases.
- Frontend fixture tests cover create project, add paper, pin evidence, add
  note, save answer, and DSH handoff.
- Playwright fixture smoke completes the project workflow.
- Secret scan passes.
- Gate 1 report is written under
  `docs/reports/workbench-research-workspace-g1.md`.

### Gate 2: Compare V1

Goal: compare project papers through a structured, evidence-first matrix.

Compare consumes Gate 1 project context. It does not create a second retrieval
system and it does not require DSH.

Required behavior:

- Add a `Compare` route reachable from Workspace.
- Let the user choose a project and a subset of saved papers.
- Let the user choose dimensions:
  - contribution
  - method
  - dataset
  - experiment
  - limitation
  - evidence strength
- Use pinned evidence, saved QA citations, and project paper metadata as the
  primary input.
- Generate a structured matrix with one row per paper and one column per
  dimension.
- Every generated cell must expose supporting chunk ids or show `No pinned
  evidence`.
- If LLM generation is unavailable, render an evidence-only matrix rather than
  failing the whole page.
- Let the user save compare runs to the project.
- Let the user send the compare context to DSH as a prepared prompt.

Required storage additions:

- `compare_runs`
- `compare_cells`

Compare output contract:

```text
CompareRun
  run_id
  project_id
  dimensions[]
  paper_ids[]
  status: completed | degraded
  cells[]
  warnings[]

CompareCell
  paper_id
  dimension
  summary
  evidence_chunk_ids[]
  note_ids[]
  confidence: evidence_backed | partial | missing
```

Evidence rules:

- Paper facts require chunk citations.
- Notes may inform interpretation only when displayed as notes.
- Missing evidence must be explicit.
- The UI must distinguish generated synthesis from raw evidence excerpts.

Completion standard:

- Backend tests cover compare matrix creation, degraded LLM fallback, evidence
  citation requirements, and persistence.
- Frontend tests cover compare route, dimension selection, matrix rendering,
  missing-evidence states, save run, and DSH prompt preview.
- Playwright fixture smoke extends Gate 1 by creating a compare run.
- Secret scan passes.
- Gate 2 report is written under
  `docs/reports/workbench-compare-g2.md`.

### Gate 3: Scoped Notes Retrieval V1

Goal: allow Ask to use project context with explicit user control.

Required behavior:

- Add project context controls to Ask:
  - active project selector
  - include pinned evidence toggle
  - include notes toggle
  - restrict retrieval to project papers toggle
- Default behavior keeps global corpus QA unchanged.
- When project context is enabled, the request includes a scoped context policy.
- Answers distinguish paper citations from note references.
- Notes are labelled as user notes and cannot satisfy paper-fact citation
  requirements.
- Pinned chunks can be included as preferred evidence, but the QA path still
  reports whether they were cited in the final answer.
- Saved QA results record the context policy used.

API additions:

```text
QaInput
  project_id?: string
  context_policy?: {
    include_pinned_evidence: boolean
    include_notes: boolean
    restrict_to_project_papers: boolean
  }

QaData
  note_refs?: string[]
  context_policy?: object
  project_context_warnings?: string[]
```

Prompting rules:

- Project notes are passed in a separate `User notes` section.
- Pinned evidence is passed in a separate `Pinned evidence` section with chunk
  ids.
- The model must be instructed that paper claims need paper chunk citations.
- The model must not present notes as external literature evidence.

Completion standard:

- Backend tests cover default QA unchanged, context policy serialization,
  note-reference separation, project-paper restriction, and LLM-unavailable
  fallback.
- Frontend tests cover Ask controls, policy toggles, answer rendering,
  note-reference badges, and saving scoped QA results.
- Playwright fixture smoke extends Gate 2 by asking with pinned evidence and
  notes enabled.
- Secret scan passes.
- Gate 3 report is written under
  `docs/reports/workbench-scoped-notes-g3.md`.

## API Summary

Gate 1 project API:

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

Gate 2 compare API:

```text
POST   /api/projects/{project_id}/compare
GET    /api/projects/{project_id}/compare-runs
GET    /api/projects/{project_id}/compare-runs/{run_id}
POST   /api/projects/{project_id}/compare-runs/{run_id}/dsh-handoff
```

Gate 3 Ask extension:

```text
POST   /api/qa
POST   /api/qa/stream
```

The existing QA endpoints are extended in a backward-compatible way. Requests
without `project_id` or `context_policy` preserve current behavior.

## UI Summary

Gate 1:

- Sidebar active-project switcher.
- `Workspace` page.
- Add-to-project actions in Library and Paper Detail.
- Pin-evidence actions in Search, Ask, and Paper Detail.
- Note editor for project, paper, and chunk targets.
- Save-answer action in Ask.

Gate 2:

- `Compare` page.
- Dimension selector.
- Paper subset selector.
- Evidence-backed comparison matrix.
- Saved compare runs panel on Workspace.
- DSH handoff from compare context.

Gate 3:

- Ask project context bar.
- Context policy toggles.
- Paper citation chips and note-reference chips rendered separately.
- Save scoped answer into the active project.

## DSH Role

DSH is used for handoff, not for core Workbench state.

Allowed DSH interactions:

- Open DSH Web.
- Copy or preview prepared prompts.
- Include project, compare, paper, chunk, note, and saved question references in
  prompts.

Disallowed DSH dependencies:

- Reading or writing DSH private session storage.
- Embedding DSH Web inside Workbench.
- Treating DSH availability as required for projects, compare, notes, or Ask.

## Reports

Each gate writes a short report after verification:

```text
docs/reports/workbench-research-workspace-g1.md
docs/reports/workbench-compare-g2.md
docs/reports/workbench-scoped-notes-g3.md
```

Each report includes:

- implementation summary
- test commands and results
- fixture smoke result
- degraded modes observed
- go/no-go status
- next gate readiness

## Verification Commands

Each gate must run:

```text
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
.venv/bin/python scripts/secret_scan.py
git status --short --branch
```

Gate 3 final verification should also perform a read-only live smoke if the
local services and credentials are available. It must not ingest, reindex,
delete, or mutate the real corpus.

## Final Acceptance Criteria

- Gate 1, Gate 2, and Gate 3 complete in order.
- All three gate reports exist and show go status.
- Workbench remains Chinese-first with English toggle.
- DSH remains optional and receives prepared context only.
- Global QA behavior remains unchanged when no project context is selected.
- Project-scoped QA separates paper citations from note references.
- Compare matrices expose evidence chunk ids or explicit missing-evidence
  states.
- No DeerFlow directory or code is reintroduced.
- No secrets, runtime credentials, real PDFs, index files, generated builds, or
  temporary smoke data are committed.
- Verification commands pass.
- Git worktree is clean after final commit.

## Deferred Work

- Deliverables V1: literature review, related work, annotated bibliography,
  evidence pack, Markdown/BibTeX/PDF export.
- DSH public prefill API integration if DSH exposes a stable supported route.
- Workspace import/export.
- Team collaboration or cloud sync.
