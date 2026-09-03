# DSH Web Paper RAG Frontend Design

## Purpose

Use DSH Web to replace DeerFlow as the primary Paper RAG frontend. The first release must cover the core research workflow that existed before the migration while improving the user experience with structured cards, evidence citations, and explicit write approval.

Completion standard:

> 用 DSH Web 替代 DeerFlow 成为 Paper RAG 的主前端，覆盖迁移前核心研究工作流，并用结构化卡片、证据引用和写入批准机制提供更好的用户体验。

## Current Context

The DeepSeek Harness migration has already removed the DeerFlow runtime path. The current runtime shape is:

```text
DSH Web
  -> Paper Research preset
  -> Native Broker
  -> private Paper RAG MCP tools
  -> src/paper_rag kernel
  -> SQLite / Qdrant / DeepSeek / artifacts
```

The frontend design must keep this boundary. DSH owns the chat shell and interaction surface. The Paper RAG kernel owns paper discovery, ingestion, retrieval, question answering, comparison, and deliverable generation.

## Goals

- Make DSH Web the default user-facing entry point for Paper RAG research.
- Preserve the migrated runtime: no DeerFlow host, DeerFlow workspace, or DeerFlow smoke path.
- Support the main workflow: discover papers, choose candidates, approve ingestion, ask evidence-backed questions, compare papers, and generate artifacts.
- Present tool results as stable, readable cards instead of raw logs.
- Keep evidence visible: answers must show citations, chunk sources, and weak/no-evidence states.
- Keep writes explicit: ingestion and artifact generation must show intended side effects and require approval.
- Keep `deepseek-v4-flash` as the model target.

## Non-Goals

- Do not recreate the old DeerFlow dashboard shell.
- Do not add a separate React app for the first release.
- Do not treat discovery candidates, web snippets, memory, or chat history as paper evidence.
- Do not move Paper RAG data ownership into DSH sessions.
- Do not commit secrets, credentials, `data/index`, runtime credentials, real PDFs, or temporary live-smoke data.

## User Experience

The user starts in DSH Web with the `Paper Research` preset selected. The assistant should guide research as one continuous chat-first flow:

```text
discover -> select -> approve ingest -> ask -> cite -> deliver -> continue
```

The first version should implement portable cards that work inside the existing DSH chat surface. A portable card is a stable structured payload plus a bounded Markdown rendering. If DSH Web later exposes native custom renderers, the same card schema can be mapped to richer components without changing Paper RAG tool contracts.

## Card Types

### Corpus Status Card

Shown after status/list operations.

Fields:
- corpus state
- indexed paper count
- recent papers
- index health
- warnings

Primary tools:
- `paper_status`
- `paper_list`

### Discovery Candidates Card

Shown after discovery operations.

Fields:
- candidate id
- title
- authors when available
- year/date
- source
- abstract or rationale summary
- ingest eligibility

Rules:
- Candidate entries are not evidence.
- The card must make selection explicit by candidate id.

Primary tools:
- `paper_discover`
- `discovery_run_get`

### Ingest Receipt Card

Shown before and after write operations.

Fields:
- requested candidate or source
- target operation
- write boundary
- expected side effects before approval
- resulting paper id after success
- stored metadata path or index location when safe to show
- failure reason on error

Rules:
- Ingestion requires approval before real writes.
- Live smoke must use isolated runtime/data paths unless the user explicitly approves writing to the real library.

Primary tools:
- `paper_ingest`
- `discovery_candidate_ingest`

### Evidence Answer Card

Shown after paper QA and comparison.

Fields:
- answer
- citation chips
- cited paper ids/titles
- cited chunk ids
- evidence count
- weak evidence or abstain flag
- trace id when available

Rules:
- Claims about papers must cite Paper RAG evidence.
- If evidence is missing or weak, the answer must say so instead of guessing.
- Chat history, discovery candidates, and web results must not be cited as paper evidence.

Primary tools:
- `paper_qa`
- `paper_compare`
- `paper_section`

### Artifact Delivery Card

Shown after deliverable generation.

Fields:
- artifact type
- generated file path or safe link
- manifest path
- citation count
- source paper ids
- file size when available
- validation status

Rules:
- Artifact content must not be embedded as base64 in chat/session history.
- Artifact paths must stay under approved project/runtime locations.

Primary tools:
- `paper_deliver`

## Component Boundaries

### DSH Preset

The `Paper Research` preset remains the user-visible mode. Its persona should instruct the model to:

- use Paper RAG tools for paper claims
- ask a concise clarification when the research target is ambiguous
- show candidate ids before ingestion
- request approval before writes
- keep `deepseek-v4-flash`

### Native Broker

The broker should remain the DSH-facing boundary. It should:

- expose a constrained tool catalog
- redact secrets from tool results and errors
- normalize Paper RAG MCP responses into card-compatible structured content
- produce the Markdown fallback rendering for DSH Web
- preserve private metadata boundaries

Tool exposure classes:

- read-only: `paper_status`, `paper_list`, `paper_search`, `paper_qa`, `paper_section`, `paper_compare`
- discovery-only: `paper_discover`, `discovery_run_get`
- approval-required writes: `paper_ingest`, `discovery_candidate_ingest`, `paper_deliver`

The first frontend release depends on exposing the discovery and write classes through the broker. Those tools must stay behind the same write-boundary and approval semantics already enforced by the MCP layer.

### Paper RAG MCP Tools

The MCP layer should remain the kernel-facing contract. It should:

- return stable structured fields needed by the cards
- keep write tools protected by the existing write boundary
- return machine-checkable error codes where possible
- avoid presentation-only logic that belongs in the broker/card layer

## Error Handling

Errors should be presented as actionable chat cards:

- missing API key: show credential category, not the secret value
- unavailable source or PDF: show source id and retry guidance
- no matching paper: suggest a narrower or broader query
- no evidence: abstain and suggest ingestion/search next steps
- write denied: preserve the planned operation and say no write occurred
- artifact failure: show failed stage and safe diagnostic metadata

Every error path must avoid leaking environment variables, credentials, raw headers, or full local secret-bearing paths.

## Approval Model

Read-only operations may run directly. Write operations must go through approval:

- paper ingestion
- artifact generation
- operations that mutate the real paper library
- operations that create durable files outside isolated smoke workspaces

The approval message must include:

- operation name
- target paper/candidate/source
- destination class
- expected files or indexes touched
- whether the operation is isolated or real-library

## Testing And Validation

Each behavior change should start with a test or validation addition before implementation.

Required validation:

- unit tests for card projection from structured tool results
- broker tests for redaction and card-compatible output
- MCP contract tests for stable fields used by the cards
- headless DSH smoke for the chat workflow: discover, select, approve isolated ingest, ask, cite, generate artifact
- secret scan
- existing migration gate validators
- no reintroduced DeerFlow runtime references

Live smoke that writes to the real paper library must remain opt-in and require explicit user approval.

## Acceptance Criteria

- DSH Web is the only required frontend for the Paper RAG workflow.
- A user can complete discovery, ingestion, QA, comparison, and artifact generation from the `Paper Research` preset without DeerFlow.
- Tool outputs appear as structured cards with stable schemas and readable Markdown fallback.
- Paper claims include citations or an explicit weak/no-evidence state.
- Write operations show side effects and require approval.
- Generated artifacts are exposed through safe paths/links, not embedded payloads.
- `deepseek-v4-flash` remains the configured model.
- Tests, live isolated smoke, validators, and secret scan pass.
- The git tree is clean after implementation commits.

## Implementation Order

1. Define the card schema and projection tests.
2. Normalize MCP result envelopes where card fields are missing.
3. Add broker-side card projection and Markdown fallback rendering.
4. Update the Paper Research preset instructions for the guided workflow.
5. Add DSH headless workflow smoke coverage.
6. Run validators, secret scan, and migration checks.

## Future Enhancements

- Native DSH Web card renderers if the web extension surface supports them cleanly.
- A research queue view for saved candidates.
- Subscription and recurring discovery management.
- Artifact browser grouped by paper, topic, and session.
- Batch comparison and literature review packs.
