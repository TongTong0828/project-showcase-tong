# Paper RAG Workbench Design

## Purpose

Build an independent Paper RAG Workbench that restores the visual research
workflow lost when the project moved away from DeerFlow, while keeping DeepSeek
Harness as the agent chat and trace surface.

The Workbench is a product layer over the existing Paper RAG kernel. It should
make common research tasks visible and efficient: inspect the local corpus,
search evidence chunks, ask cited questions, discover candidate papers, and
approve ingestion. It must not reintroduce DeerFlow runtime code or fork the
Paper RAG business logic.

## Current Context

The current migrated runtime is:

```text
DSH Web
  -> Paper Research preset
  -> Native Broker
  -> Paper RAG MCP registry/tools
  -> src/paper_rag kernel
  -> SQLite / Qdrant / DeepSeek / artifacts
```

The previous DSH frontend release intentionally used the DSH chat shell and
portable Markdown cards rather than recreating the old DeerFlow dashboard. That
path is now functional, but it still feels like a general agent console instead
of a Paper RAG product. This spec adds a separate Workbench for the product
experience and keeps DSH Web for agent conversation, trace, and session logs.

## Goals

- Provide a dedicated local web UI for the Paper RAG research workflow.
- Preserve the migrated runtime: no DeerFlow host, gateway, workspace, or smoke
  path returns.
- Reuse the existing MCP registry and `src/paper_rag` kernel as the single
  source of paper operations.
- Make the core workflow visible without requiring prompt-only interaction:
  overview, library, evidence search, cited QA, discovery, and approved ingest.
- Keep DSH Web available as the agent chat, trace, and session-log companion.
- Keep `deepseek-v4-flash` as the model target.
- Keep write operations explicit and approval-gated.
- Keep secrets, real PDFs, runtime credentials, `data/index`, and generated
  runtime state out of git.

## Non-Goals

- Do not embed this UI inside DSH Web or depend on private DSH frontend internals.
- Do not remove DSH Web, the `Paper Research` preset, or DSH trace/session
  workflows.
- Do not recreate DeerFlow auth, gateway middleware, dashboard, or deployment
  topology.
- Do not add multi-user SaaS authentication in the first Workbench release.
- Do not build Compare or Deliverables as first-class MVP screens. Their API
  contracts should remain compatible, but the first visual release focuses on
  corpus, search, QA, discovery, and approved ingestion.
- Do not perform automated live smoke writes against the real paper library
  without explicit user approval.

## Recommended Architecture

Use a separate Workbench app beside the DSH integration:

```text
Browser
  -> Paper RAG Workbench SPA
       -> Workbench API adapter
            -> paper_rag.mcp.registry.call_tool(...)
                 -> src/paper_rag kernel

Browser
  -> DSH Web
       -> Paper Research preset
            -> native broker
                 -> the same MCP registry and kernel
```

The Workbench and DSH Web share the Paper RAG kernel but do not share UI state.
Workbench-originated operations expose Workbench request traces and MCP
`trace_id`s. DSH-originated operations continue to expose DSH session traces in
DSH Web.

### Code Layout

- `integrations/paper-rag-workbench/`: Vite + React + TypeScript SPA.
- `src/paper_rag/workbench/`: FastAPI adapter, API schemas, approval helpers,
  and server-side credential bridge.
- `tests/test_workbench_api.py`: FastAPI contract and approval tests.
- `integrations/paper-rag-workbench/src/`: routes, API client, UI components,
  and test fixtures.
- `integrations/paper-rag-workbench/tests/`: component and Playwright tests.
- `scripts/start_workbench.py` or `make workbench`: local launcher for API and
  SPA during development.

### Runtime Shape

Development mode may use two local loopback ports:

- Workbench UI: `http://127.0.0.1:3090`
- Workbench API: `http://127.0.0.1:3091`

The Vite dev server proxies `/api/*` to the FastAPI adapter. Packaged
production mode may serve the built SPA from the FastAPI server on one port.

DSH Web remains on `http://127.0.0.1:3080` by default.

## Product UX

The first screen should be the working dashboard, not a marketing landing page.
The UI should feel like a quiet research workbench: dense, scannable, and built
for repeated use.

Primary navigation:

- Overview
- Library
- Search
- Ask
- Discover
- DSH Chat

Compare and Deliverables can appear as disabled or secondary future entries only
if they do not distract from the MVP workflow.

### Overview

Purpose: answer "what is in my corpus and is it healthy?"

Content:

- paper count
- chunk count
- SQLite availability
- LLM configured status
- configured chat model
- recent papers
- warnings from `paper_status`
- quick actions into Search, Ask, Discover, and DSH Chat

Data sources:

- `paper_status`
- `paper_list`

### Library

Purpose: browse indexed papers and choose research targets.

Content:

- table of indexed papers
- title, paper id, arXiv id, year when available, chunk count
- local filter by title, id, and arXiv id
- paper detail drawer
- actions: search within paper, ask about paper, read section

MVP detail drawer:

- metadata from `paper_list`
- abstract or introduction through `paper_section` when requested
- chunk count and safe identifiers

Data sources:

- `paper_list`
- `paper_section`

### Search

Purpose: inspect evidence before asking the model to synthesize.

Content:

- natural-language query input
- top-k control
- optional year range controls
- evidence chunk cards
- paper title/id, page, chunk id, snippet, score if available
- copyable citation token, such as `chunk:<id>`
- no-results state with guidance to broaden query or ingest more papers

Data source:

- `paper_search`

### Ask

Purpose: produce an answer with visible citations and evidence.

Content:

- question input
- optional selected paper constraints
- top-k control
- answer panel
- citation chips
- cited paper/chunk list
- evidence drawer with chunk text and page metadata
- weak-evidence or no-evidence state
- "Open in DSH Chat" action that copies a prepared prompt and opens DSH Web

Data source:

- `paper_qa`

Rules:

- Claims about papers must cite indexed Paper RAG evidence.
- Discovery candidates, chat history, web snippets, and memory are not answer
  evidence.
- If `paper_qa` returns weak or no evidence, the UI must show that state instead
  of styling the answer as authoritative.

### Discover

Purpose: find candidate papers and explicitly approve ingestion.

Content:

- topic input
- source selector, with arXiv enabled first
- max candidate control
- discovery run metadata
- candidate table with candidate id, title, authors when available, year/date,
  source, rank/rationale, and ingest eligibility
- selection controls for up to five candidates
- approval dialog before `discovery_candidate_ingest`

Data sources:

- `paper_discover`
- `discovery_run_get`
- `discovery_candidate_ingest`

Rules:

- Candidates are candidate-only metadata, not answer evidence.
- The approval dialog must name the operation, candidate ids, destination class,
  expected write side effects, and whether the target is isolated or the real
  library.
- The write button must remain disabled until the user explicitly confirms the
  side effects.

### DSH Chat Bridge

Purpose: keep the agentic surface available without making the Workbench depend
on DSH internals.

MVP behavior:

- a persistent "Open DSH Chat" link to `http://127.0.0.1:3080`
- context-aware "Copy prompt for DSH" actions from Ask, Search, Library, and
  Discover screens
- clear labeling that DSH trace/session logs are available for DSH-originated
  chats, while Workbench calls show Workbench request traces and MCP `trace_id`s

The MVP should not attempt to deep-link into private DSH sessions.

## API Adapter Contract

The Workbench API adapter is a thin local server. It must not duplicate Paper
RAG business logic. It validates HTTP input, builds an `McpRequestContext`, calls
`paper_rag.mcp.registry.call_tool`, and returns the MCP envelope.

Recommended endpoints:

- `GET /api/health`
- `GET /api/status`
- `GET /api/papers?limit=...`
- `POST /api/search`
- `POST /api/qa`
- `POST /api/section`
- `POST /api/discover`
- `GET /api/discovery-runs/{run_id}`
- `POST /api/ingest/candidates`

Response shape:

```json
{
  "ok": true,
  "tool": "paper_qa",
  "trace_id": "trace-id-or-null",
  "evidence_role": "answer_evidence",
  "warnings": [],
  "data": {}
}
```

Error responses should preserve the MCP error envelope where possible:

```json
{
  "ok": false,
  "tool": "paper_qa",
  "error": {
    "code": "UNAVAILABLE",
    "message": "safe diagnostic message",
    "retryable": false
  }
}
```

### Toolset

The Workbench adapter should run with the `research` MCP toolset for MVP. The
UI decides which endpoints are visible, and write endpoints still require an
approval boundary before the MCP write tool is called.

### Credentials

The API server resolves credentials server-side only.

Resolution order:

1. inherited process environment (`DEEPSEEK_API_KEY` or `OPENAI_API_KEY`)
2. repo-managed DSH credentials file when explicitly configured by the launcher

The resolved value must never be returned to the browser, logged, embedded in a
session payload, or committed. Status endpoints may return only configured/not
configured and source class, never the secret value.

### Model Configuration

The launcher must set:

- `OPENAI_BASE_URL=https://api.deepseek.com`
- `CHAT_MODEL=deepseek-v4-flash`
- `SMALL_MODEL=deepseek-v4-flash`

The Workbench must not switch to a pro model.

## Approval Model

Read-only endpoints may run directly:

- status
- list
- search
- QA
- section
- discovery
- discovery run lookup

Write endpoints require explicit approval:

- `discovery_candidate_ingest`
- MVP-hidden `paper_ingest` when it becomes visible in the Workbench
- MVP-hidden `paper_deliver` when it becomes visible in the Workbench

The Workbench write flow:

1. UI prepares the write request and side-effect summary.
2. UI shows an approval dialog.
3. User confirms the operation.
4. API creates a request boundary for that user-confirmed operation.
5. API calls the MCP write tool with `request_boundary_id`, `conversation_id`,
   and `tool_call_id`.
6. API returns the MCP receipt/result envelope.

The server must reject write endpoint calls without an approval payload and
request boundary. Browser state alone is not approval.

## Data And Secret Boundaries

- Do not commit `.env`, API keys, runtime credentials, `data/index`, real PDFs,
  DSH sessions, or temporary smoke data.
- Do not expose full local secret-bearing paths in the browser.
- Do not serve raw PDFs from arbitrary paths.
- Local PDF ingestion, when added, must stay under `PAPER_RAG_IMPORT_ROOT`.
- Artifact links, when added, must stay under `PAPER_RAG_ARTIFACT_ROOT`.
- API responses must redact secret-shaped values and authorization headers.
- Search and QA evidence may expose bounded chunk text, paper ids, chunk ids,
  page numbers, and safe metadata.

## Visual Design Direction

The Workbench should be utilitarian and research-focused:

- persistent left navigation or compact top navigation
- dense tables for papers and candidates
- evidence chunks as repeated cards with stable metadata rows
- citation chips for chunks
- drawers for paper detail and evidence expansion
- modal dialog for approval
- restrained colors with clear status accents
- no marketing hero page
- no decorative gradients or oversized cards

The first viewport should show actual corpus state, not explanatory text.

## Error Handling

Every error should lead to a next action:

- missing credentials: show "LLM not configured" and point to local credential
  setup without revealing paths or values
- empty corpus: suggest Discover or DSH Chat
- no search results: suggest broader query or discovery
- weak/no QA evidence: show evidence state and suggest Search or Discover
- write denied: show that no write occurred and preserve the draft operation
- ingest failure: show candidate ids and safe failure reason
- backend unavailable: show retry and API health status

## Testing And Validation

Behavior changes should be test-first where practical.

Backend validation:

- FastAPI route tests with mocked `call_tool`
- schema tests for each endpoint
- approval rejection tests for write endpoints without a boundary
- credential status tests that prove no secret value is serialized
- MCP contract regression tests for fields consumed by the UI

Frontend validation:

- component tests for Corpus Status, Paper Table, Evidence Chunk, Citation Chips,
  QA Answer, Candidate Table, and Approval Dialog
- API client tests for MCP success and error envelopes
- Playwright smoke using fixture responses:
  - Overview loads corpus status
  - Library filters papers
  - Search renders evidence chunks
  - Ask renders answer, citations, and evidence drawer
  - Discover requires approval before ingest

Live validation:

- read-only live smoke may run against the current local corpus when credentials
  are available
- write smoke must use isolated data paths unless the user explicitly approves
  writing to the real library
- DSH headless smoke remains part of migration validation and should continue
  to prove the agent path

Repository validation:

- Python tests
- frontend tests
- Playwright smoke
- DSH integration tests
- migration validators affected by the change
- `scripts/secret_scan.py`
- clean git status

## Implementation Phases

### Phase 1: Workbench API Adapter

Add the FastAPI adapter, typed request/response schemas, read endpoints, write
approval rejection, credential status redaction, and backend tests.

### Phase 2: Frontend Skeleton

Create the Vite/React app, route shell, navigation, API client, fixture mode,
and first Playwright smoke for loading Overview.

### Phase 3: Corpus And Evidence UX

Implement Overview, Library, Search, and shared evidence/citation components.

### Phase 4: Cited QA UX

Implement Ask with paper constraints, answer panel, citation chips, evidence
drawer, weak/no-evidence states, and DSH prompt-copy bridge.

### Phase 5: Discovery And Approval UX

Implement Discover, candidate table, selection, approval dialog, approved
candidate ingest, and ingest receipt rendering.

### Phase 6: Launcher, Docs, And Validation

Add the local launcher, README updates, full validation commands, and smoke
reports. Confirm that DSH Web still starts independently and that no DeerFlow
runtime path has returned.

## Acceptance Criteria

- Workbench starts locally and shows the corpus overview as the first screen.
- A user can inspect the library without using the chat box.
- A user can search indexed evidence and inspect bounded chunk text with paper,
  page, and chunk metadata.
- A user can ask a question and see an answer, citation chips, and expandable
  evidence.
- A user can discover candidate papers and ingest selected candidates only after
  explicit approval.
- Workbench exposes a clear bridge to DSH Chat without depending on private DSH
  session internals.
- DSH Web and the `Paper Research` preset continue to work.
- The implementation uses `deepseek-v4-flash`, not a pro model.
- No DeerFlow runtime path is restored.
- Tests, smoke checks, validators, secret scan, and git cleanliness pass.

## Future Enhancements

- Compare screen with a multi-paper matrix.
- Deliverables screen with artifact history, manifests, and safe downloads.
- Saved research sessions shared between Workbench and DSH through an explicit
  public contract.
- Data quality dashboard for duplicate chunks, parser artifacts, and section
  coverage.
- Subscription and proactive inbox views from the existing proactive modules.
