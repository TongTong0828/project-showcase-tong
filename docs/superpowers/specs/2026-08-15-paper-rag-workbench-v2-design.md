# Paper RAG Workbench V2 Design

## Purpose

Evolve Paper RAG Workbench from an MVP research interface into a reliable local
research cockpit. The next release should make corpus health, paper inspection,
evidence provenance, and DSH handoff visible enough that a user can understand
why an answer succeeded or failed without reading terminal logs.

This spec extends the existing independent Workbench. It does not replace DSH
Web, reintroduce DeerFlow, or fork Paper RAG business logic.

## Current Context

The current project has two UI surfaces:

```text
Paper RAG Workbench
  -> FastAPI Workbench adapter
  -> paper_rag.mcp.registry.call_tool(...)
  -> src/paper_rag kernel
  -> SQLite / Qdrant / DeepSeek / artifacts

DSH Web
  -> Paper Research preset
  -> Native Broker
  -> same MCP registry and kernel
```

The Workbench MVP already supports:

- Overview: corpus count, chunk count, model, credential status.
- Library: paper list, text filter, section drawer.
- Search: evidence search with chunk metadata.
- Ask: cited QA with evidence cards.
- Discover: candidate discovery and approval-gated ingest.
- DSH Chat bridge: opens DSH Web as the chat and trace companion.
- The core already has `paper_rag.rag.qa_stream`, but Workbench currently uses
  blocking QA and does not expose streaming progress or agent stages.

The latest live smoke exposed the next reliability needs:

- Qdrant may be down or locked, so users need clear index-health diagnostics.
- `paper_search` needs fallback paths and visible degraded-state warnings.
- Section/chunk quality issues such as duplicate chunks, HTML comments, and
  parser artifacts should be discoverable in the UI.
- Ask can now generate real answers, but citations need better drilldown,
  page context, and audit affordances.
- DSH is still useful for long-running agent work, but Workbench should remain
  the primary Paper RAG front door.

## Goals

- Add a Workbench health surface that diagnoses SQLite, Qdrant, FTS, credentials,
  model configuration, duplicate chunks, parser artifacts, and index alignment.
- Add a first-class Paper Detail view with metadata, sections, chunks, and local
  evidence actions.
- Add Citation Drilldown so every answer citation can be inspected in context.
- Add streaming Ask with a visible agent timeline so users can see retrieval,
  reflection, abstain, generation, and finalization progress before the full
  answer is done.
- Add a stronger DSH handoff model that sends selected papers, chunks, and
  questions into DSH as a prepared prompt while keeping DSH as a separate surface.
- Preserve explicit approval for all real writes.
- Keep `deepseek-v4-flash` as the configured model.
- Keep all diagnostics secret-safe: no API keys, raw credential files, real PDFs,
  runtime sessions, or `data/index` outputs are committed.

## Non-Goals

- Do not re-create DeerFlow routes, host runtime, auth, gateway middleware, or
  dashboard code.
- Do not embed DSH Web inside Workbench or rely on DSH private frontend internals.
- Do not implement multi-user auth, cloud sync, billing, or SaaS sharing.
- Do not make Compare or Deliverables primary V2 screens. They can be represented
  as future navigation entries or contracts, but this V2 focuses on diagnosis,
  inspection, provenance, and handoff.
- Do not run automated real-library write smoke tests without explicit approval.
- Do not expose credentials, environment secret values, local PDF content paths,
  or DSH session internals in browser-visible diagnostics.

## Recommended Approach

Implement V2 as an incremental extension of the current Workbench:

```text
Browser
  -> Workbench SPA
       -> Existing Workbench API adapter
            -> Existing MCP tools where possible
            -> Small read-only diagnostics helpers where MCP has no safe tool
                 -> SQLite / config / Qdrant metadata only
       -> DSH Chat remains separate at http://127.0.0.1:3080
```

This approach is preferred because it keeps the current architecture stable and
adds observability around the exact failure modes already seen in live testing.
It also avoids creating a second Paper RAG implementation in the frontend.

### Alternatives Considered

1. **Workbench-only product expansion**: Add every former DeerFlow capability to
   Workbench immediately, including Compare, Deliverables, inbox, and feedback.
   This would be attractive eventually, but too broad for one reliable release.

2. **DSH-first expansion**: Keep most workflows in DSH cards and use Workbench
   only as a thin status page. This would be faster, but it keeps the user in a
   prompt-first experience and does not solve evidence inspection or index-health
   visibility.

3. **Recommended V2 cockpit**: Add diagnosis, paper detail, citation drilldown,
   and DSH handoff. This creates the most leverage with the least new surface
   area and directly addresses the observed data-quality and retrieval issues.

## Product Scope

### 1. Index Health

Purpose: answer "is my corpus usable, and if not, where is it broken?"

Add a navigation item named `Health` or make the Overview page contain a
prominent Health panel. The page should show:

- SQLite status: path redacted to project-relative form, paper count, chunk
  count, FTS availability.
- Qdrant status: configured mode, server reachable or embedded path locked,
  collection names, dense-search availability.
- LLM status: configured base URL hostname, model name, credential source,
  generation-ready boolean.
- Retrieval status: whether dense, sparse, and hybrid search are available.
- Corpus quality: duplicate chunk samples, chunk count by paper, parser artifact
  counts, missing common sections where detectable.
- Last diagnostic run time and warnings.

The page must distinguish:

- `healthy`: all expected services/indexes are available.
- `degraded`: at least one subsystem is unavailable but fallback exists.
- `blocked`: core read or generation path cannot work.

V2 should start with read-only diagnostics. Rebuild/reindex actions can be shown
as disabled or approval-gated future actions unless the implementation plan
explicitly adds isolated-path rebuild tests.

### 2. Paper Detail

Purpose: make one paper inspectable without relying on chat.

Add a detail route or drawer reachable from Library, Search, Ask citations, and
Discover-ingested receipts.

Content:

- Title, paper id, arXiv id, year if available, chunk count.
- Section list derived from indexed chunks and `paper_section`.
- Abstract and Introduction quick readers.
- Chunk table with page, section, chunk id, preview text, parser warnings.
- Actions: Ask about this paper, Search within this paper, Copy paper id, Open
  selected chunks in DSH.

Paper Detail should not assume every paper has clean section names. If sections
are missing or ambiguous, show a `Section metadata incomplete` warning and offer
chunk/page browsing instead.

### 3. Citation Drilldown

Purpose: make answer provenance inspectable and trustworthy.

Enhance Ask and Search results so citation chips and chunk cards can open a
drilldown panel with:

- Full chunk text.
- Paper title/id.
- Page and section metadata if present.
- Neighboring chunks from the same paper/page when available.
- Retrieval score fields shown with labels such as dense, sparse, RRF, rerank.
- Parser quality warnings for that chunk.
- Copy citation token.
- Open paper detail.

The Answer panel should visually distinguish:

- generated answer text,
- cited chunks,
- retrieved-but-uncited evidence,
- weak/no-evidence states,
- discovery candidates that are explicitly not answer evidence.

### 4. DSH Handoff

Purpose: keep DSH as the long-form agent companion without making it the main UI.

Add a `Send to DSH` or `Open in DSH` action from:

- Ask page answer.
- Search result selection.
- Paper Detail selected chunks.
- Health diagnostics warnings.

The action should prepare a prompt such as:

```text
基于 Paper RAG Workbench 中选定的论文/证据继续研究：
- Papers: ...
- Chunks: ...
- Question: ...
请使用 Paper RAG 工具回答，并保留证据引用。
```

MVP handoff may copy the prompt and open DSH Web. A later release can add shared
trace ids or a local handoff queue if DSH exposes a stable public route/API for
prefilling messages. Workbench must not depend on DSH private session internals.

### 5. Write Approval Model

Keep the current approval boundary for writes:

- Discover candidates are candidate-only until ingested.
- `Ingest selected` opens an approval dialog naming exact side effects.
- No frontend path can call ingest without an approval payload.
- No health or paper detail action may rebuild, delete, or write to the real
  library without explicit approval.

V2 may add disabled future actions for rebuild/reindex, but implementation must
include backend tests proving they cannot write without approval.

### 6. Streaming Ask And Agent Timeline

Purpose: recover the live research-assistant feel without reintroducing
DeerFlow.

Ask should support a streaming path that emits stage events and answer chunks:

- `start`: request accepted and trace id created.
- `intent`: question classified.
- `rewrite`: retrieval query generated.
- `retrieved`: evidence chunks found.
- `reflect`: reflection/follow-up decision when enabled.
- `abstain`: evidence confidence decision.
- `answer_chunk`: generated answer text.
- `done`: final answer, citations, chunks, abstain, paper ids, query resolution.
- `error`: stream failure with a safe message.

Every non-token stage should include `trace_id`, `stage`, `status`, `summary`,
and `elapsed_ms` when available. `answer_chunk` should include `trace_id`,
`stage: "answer"`, and `text`.

Workbench should render these events as:

- a live `Agent Timeline` on the Ask page,
- incrementally growing answer text,
- final citation chips and drilldown once `done` arrives,
- a clear fallback path to blocking `/api/qa` if streaming is unavailable.

The streaming path belongs to Workbench's FastAPI adapter and React app. It must
not use DeerFlow gateway routes or DeerFlow frontend code.

## API Design

Reuse existing endpoints where possible:

- `GET /api/status`
- `GET /api/papers`
- `POST /api/search`
- `POST /api/qa`
- `POST /api/qa/stream`
- `POST /api/section`
- `POST /api/discover`
- `POST /api/ingest/candidates`

Add read-only Workbench endpoints:

### `GET /api/health/index`

Returns structured diagnostics:

```ts
type IndexHealthData = {
  status: "healthy" | "degraded" | "blocked";
  sqlite: {
    available: boolean;
    paper_count: number;
    chunk_count: number;
    fts_available: boolean;
  };
  qdrant: {
    configured: boolean;
    mode: "server" | "embedded" | "none";
    reachable: boolean;
    degraded_reason?: string;
  };
  retrieval: {
    dense_available: boolean;
    sparse_available: boolean;
    hybrid_available: boolean;
  };
  llm: {
    configured: boolean;
    chat_model: string;
    base_url_host?: string;
    credential_source?: "env" | "file" | null;
  };
  corpus_quality: {
    duplicate_chunk_count: number;
    parser_artifact_count: number;
    missing_section_count: number;
    samples: HealthSample[];
  };
  warnings: string[];
};
```

### `GET /api/papers/{paper_id}`

Returns paper metadata and section/chunk summaries. It should URL-decode the
paper id and validate it as a bounded string.

### `GET /api/chunks/{chunk_id}`

Returns chunk detail and optional neighbor chunks. It must not return local PDF
file paths or raw artifact paths.

### `POST /api/dsh/handoff`

Optional read-only helper that returns a prepared prompt and DSH URL. The server
does not submit anything to DSH.

### `POST /api/qa/stream`

Returns `text/event-stream` frames from `paper_rag.rag.async_api.stream_answer_async`.
It accepts the same payload shape as `POST /api/qa` and is read-only.

```ts
type QaStreamEvent =
  | { event: "start"; data: StageEventData }
  | { event: "intent"; data: StageEventData & Record<string, unknown> }
  | { event: "rewrite"; data: StageEventData & { queries?: string[]; keywords?: string } }
  | { event: "retrieved"; data: StageEventData & { iter?: number; n_chunks?: number } }
  | { event: "reflect"; data: StageEventData & Record<string, unknown> }
  | { event: "abstain"; data: StageEventData & Record<string, unknown> }
  | { event: "answer_chunk"; data: { trace_id: string; stage: "answer"; text: string } }
  | { event: "done"; data: StageEventData & QaData & { paper_ids?: string[] } }
  | { event: "error"; data: StageEventData & { message: string } };

type StageEventData = {
  trace_id: string;
  stage: string;
  status: "running" | "completed" | "failed" | "skipped";
  summary: string;
  elapsed_ms?: number;
};
```

## Frontend Design

Navigation becomes:

- Overview
- Health
- Library
- Search
- Ask
- Discover
- DSH Chat

If space is tight, Health can be a tab under Overview, but it should be visible
from the first screen when there is a degraded state.

New components:

- `HealthSummary`
- `DiagnosticCard`
- `QualityIssueTable`
- `PaperDetailPanel`
- `ChunkDetailPanel`
- `ScoreBreakdown`
- `AgentTimeline`
- `DshHandoffDialog`
- `WarningBanner`

New frontend helpers:

- `api/qaStream.ts`: fetch-based SSE parser, stream reader, and pure reducer.
- `AgentTimeline`: stage list with status, summaries, and elapsed time.

The Ask page should prefer streaming when available, but keep the existing
blocking client method as a fallback.

Layout principles:

- Keep the first viewport operational, not a landing page.
- Use restrained dashboard styling consistent with the current Workbench.
- Avoid nested cards; page sections are full-width bands or simple panels.
- Long chunk ids, titles, warnings, and generated text must wrap cleanly.
- No decorative gradients or non-functional visual noise.

## Data Quality Rules

V2 should make data quality visible but not silently mutate the corpus.

Detected issues:

- Duplicate chunks: same normalized text with multiple chunk ids.
- Parser artifacts: HTML comments such as `<!-- page 2 -->`, repeated
  `Preprint.`, obvious page markers in evidence text.
- Missing sections: common requested sections such as abstract, introduction,
  method, limitations return no chunks for an indexed paper.
- Qdrant mismatch: SQLite has chunks but dense search is unavailable or returns
  zero while sparse search succeeds.

Actions:

- Read-only diagnostics are allowed by default.
- Fixing/reindexing requires a separate approval-gated implementation plan.
- UI should explain degraded mode in plain language.

## Error Handling

- API errors return existing MCP-style envelopes where possible.
- Health diagnostics return partial results if one subsystem fails.
- Search and Ask show when dense retrieval is unavailable but sparse fallback
  supplied evidence.
- If LLM generation is unavailable, Ask shows evidence-only mode with chunks and
  a clear generation warning.
- If the streaming QA endpoint fails before `done`, Ask should show the last
  completed stages, a safe error message, and a retry path that can use blocking
  `/api/qa`.
- If DSH is unavailable, handoff still provides a copyable prompt.
- The frontend must never show raw secret values, credential file contents, or
  runtime session data.

## Testing Strategy

Backend:

- Unit tests for index-health diagnostics with fake SQLite/Qdrant/LLM states.
- Tests that diagnostics redact paths and never serialize secret values.
- Tests for paper detail and chunk detail endpoints.
- Tests for normalized `qa_stream` event contract and Workbench SSE framing.
- Tests that write-like actions remain approval-gated.
- Regression tests that `paper_search` fallback is represented in response
  warnings or metadata.

Frontend:

- Component tests for health cards, warning banners, paper detail, chunk detail,
  Agent Timeline, and DSH handoff dialog.
- Page tests for Health, Paper Detail, Citation Drilldown, streaming Ask, and
  degraded Search.
- Fixture-mode Playwright smoke covering Overview -> Health -> Library ->
  Paper Detail -> Search -> Ask -> Agent Timeline -> Citation Drilldown ->
  Discover approval.

Integration:

- DSH tests/typecheck/smoke remain required.
- Migration/parity tests continue to assert no DeerFlow runtime path returns.
- Secret scan remains mandatory.
- Live write smoke remains opt-in only.

## Rollout Plan

1. Add read-only backend diagnostics and tests.
2. Add frontend Health page with fixture and live degraded-state rendering.
3. Add Paper Detail endpoint and UI.
4. Add Chunk Detail / Citation Drilldown.
5. Add DSH handoff dialog.
6. Normalize QA stream events and expose Workbench SSE.
7. Add frontend streaming Ask and Agent Timeline.
8. Extend Playwright fixture smoke and regression tests.
9. Run backend, frontend, DSH, migration, and secret-scan validation.

Each step should be committed separately and should preserve a clean git tree.

## Acceptance Criteria

- Workbench first screen clearly shows whether the corpus is healthy or degraded.
- User can inspect one paper's sections and chunks from Library.
- User can click an answer citation and see the exact chunk, paper, page, and
  surrounding context.
- User can ask a question and see agent-stage progress plus incremental answer
  text before final citations arrive.
- User can understand when Qdrant is unavailable and whether sparse fallback is
  being used.
- User can copy/open a DSH handoff prompt based on selected paper/chunk context.
- No write path bypasses approval.
- `deepseek-v4-flash` remains the configured model.
- No DeerFlow runtime path is restored.
- Secret scan passes.
- Workbench tests, Playwright fixture smoke, DSH regressions, and migration
  regressions pass.

## Implementation Constraints

- Use the existing Workbench FastAPI adapter and React app.
- Implement streaming through Workbench-owned `/api/qa/stream`; do not route it
  through DeerFlow.
- Reuse MCP tools first. Add Workbench-only read endpoints only for diagnostics
  or detail views that are not appropriate as model-visible tools.
- Do not add dependencies unless they remove clear complexity.
- Do not commit generated `dist`, `node_modules`, `data/index`, runtime
  credentials, DSH sessions, real PDFs, or temporary smoke data.
- Do not change the DSH preset model away from `deepseek-v4-flash`.
- Do not stop or remove DSH Web; keep it as the trace/chat companion.
