# Agent Trace Streaming V1 Design

- **Status**: draft, approved for planning
- **Date**: 2026-08-15
- **Scope**: DeerFlow Paper RAG workspace streaming QA experience
- **Owner**: paper_rag team
- **Target milestone**: V1 full streaming trace
- **Estimated effort**: 1-2 engineering days

---

## 1. Goals

Make Paper RAG QA visibly progress while the agent runs, so users can learn and debug the agent control process by watching a real execution instead of waiting on an opaque loading state.

V1 must solve four user-facing problems:

1. Long-running QA appears stuck because the UI waits for a complete response.
2. Frontend or gateway timeouts can look like generic failures.
3. Users cannot tell which agent stage is currently running.
4. The final answer does not expose enough stage detail to explain quality issues.

The V1 experience should show:

```text
Question -> intent -> rewrite -> retrieve -> reflect -> abstain -> token stream -> done/error
```

## 2. Non-Goals

- Do not tune retrieval quality, reranker thresholds, chunking, or abstain calibration in this V1.
- Do not replace the existing `/api/paper_rag/qa/sync` endpoint; keep it as fallback and test coverage.
- Do not make MCP `paper_qa` stream through DeepSeek Harness native tool calls in V1.
- Do not add persistent run storage for every stream event.
- Do not redesign the whole Paper RAG workspace page.

## 3. Current State

### 3.1 Backend

The DeerFlow gateway already exposes:

- `POST /api/paper_rag/qa`: SSE endpoint backed by `paper_rag.rag.qa_stream.stream_answer`.
- `POST /api/paper_rag/qa/sync`: blocking endpoint backed by `paper_rag.rag.qa_agentic.answer`.

The stream currently emits useful events:

- `intent`
- `rewrite`
- `retrieved`
- `reflect`
- `abstain`
- `answer_chunk`
- `done`
- `error`

Gaps:

- Events are not normalized around a common stage/status/timing contract.
- Some events do not carry enough information for a frontend timeline.
- Stream-level trace id is not available early enough for feedback and debugging.
- Stage elapsed time is not consistently surfaced.

### 3.2 Frontend

The Paper RAG page currently calls `/api/paper_rag/qa/sync` from `ask()`.

The page already renders a static `Loop Trace` section after a completed sync response. This is useful, but it only appears after the long-running request finishes.

Gaps:

- No incremental answer rendering.
- No live timeline while the agent is running.
- No stage-specific error state.
- No SSE parser or stream cancellation/ignore behavior for repeated asks.

## 4. Proposed Approach

Use the existing `/api/paper_rag/qa` SSE endpoint as the default Ask path, and upgrade the UI from post-hoc trace display to a live Agent Timeline.

V1 has two implementation tracks:

1. **Backend event contract hardening**
   Normalize stream events so the frontend can reliably render stages, timings, trace ids, and errors.

2. **Frontend streaming timeline**
   Replace the sync Ask path with SSE consumption, update the answer token by token, and render stage progress as events arrive.

`/api/paper_rag/qa/sync` remains available for fallback and tests.

## 5. Backend Design

### 5.1 Stream Event Envelope

Each SSE event keeps the existing SSE event name while making its JSON data renderable as a stage payload.

Common fields:

```json
{
  "trace_id": "trace-id-if-known",
  "stage": "retrieve",
  "status": "running|completed|failed|skipped",
  "elapsed_ms": 123,
  "summary": "Retrieved 8 chunks"
}
```

Rules:

- `trace_id` is generated once per stream and included from `start` onward.
- `stage` must be stable and frontend-friendly.
- `status` is required for stage events except `answer_chunk`.
- `elapsed_ms` is measured from the start of that stage when available.
- `summary` is short, human-readable, and safe to show in UI.
- Existing event-specific fields remain available.

### 5.2 Event Types

#### `start`

Emitted immediately after request resolution starts.

```json
{
  "trace_id": "abc123",
  "stage": "start",
  "status": "completed",
  "summary": "Started Paper RAG QA"
}
```

Purpose: lets the frontend show activity quickly and distinguish a dead connection from slow model work.

#### `intent`

Emitted after intent classification.

Required fields:

- `trace_id`
- `intent`
- `top_k`
- `max_iter`
- `elapsed_ms`

#### `rewrite`

Emitted after first query rewrite.

Required fields:

- `trace_id`
- `queries`
- `keywords`
- `elapsed_ms`

#### `retrieved`

Emitted after each retrieval round.

Required fields:

- `trace_id`
- `iter`
- `query`
- `n_chunks`
- `elapsed_ms`

Optional fields:

- bounded chunk previews for the top retrieved evidence, if cheap and already available

#### `reflect`

Emitted after each reflection call.

Required fields:

- `trace_id`
- `iter`
- `sufficiency`
- `follow_up`
- `reason`
- `elapsed_ms`

#### `abstain`

Emitted after evidence quality decision.

Required fields:

- `trace_id`
- `decision`
- `evidence_score`
- `n_chunks`
- `elapsed_ms`

#### `answer_chunk`

Emitted for generated answer text.

Required fields:

- `trace_id`
- `text`

The frontend appends `text` to the current visible answer.

#### `done`

Emitted exactly once for successful completion, including no-evidence completion.

Required fields:

- `answer`
- `citations`
- `abstain`
- `n_chunks`
- `query_resolution`
- `paper_ids`
- `trace_id`

Optional fields:

- `evidence_chunks`
- `evidence_selection`
- `suspicious`
- `memory`

#### `error`

Emitted for recoverable stream failures.

Required fields:

- `trace_id` if the stream created one before failure
- `stage`
- `status: "failed"`
- `message`
- `elapsed_ms` if available

The stream ends after an `error` event.

### 5.3 Timeout And Heartbeat Behavior

V1 does not introduce server-side cancellation machinery. It avoids silent periods with the following requirements:

- Emit `start` before any expensive work.
- Emit stage completion immediately after each stage.
- If a single model call can take a long time, the UI still shows the current stage as running.

No custom heartbeat is required for initial implementation. If manual smoke reveals proxy or browser disconnects during long model calls, configure the existing `EventSourceResponse` ping interval at the gateway layer without changing the frontend contract.

### 5.4 Backward Compatibility

- Existing event names remain compatible.
- Existing tests that assert `intent`, `answer_chunk`, and `done` continue to pass.
- `/api/paper_rag/qa/sync` response shape remains unchanged.
- Existing non-streaming feedback continues to use final `trace_id`.

## 6. Frontend Design

### 6.1 Ask Flow

The `ask()` function should:

1. Trim and validate the question.
2. Reset previous answer, trace, feedback, and stream error.
3. Create a new local request id.
4. Open a streaming POST request to `/api/paper_rag/qa`.
5. Parse SSE events incrementally.
6. Ignore events from old requests if the user asks again.
7. Append `answer_chunk.text` to the visible answer.
8. Update Agent Timeline stages as stage events arrive.
9. On `done`, finalize citations, trace id, abstain, memory, and evidence metadata.
10. On `error` or stream failure, mark the current stage failed and show a retryable error.

Because browser `EventSource` does not support POST bodies, the frontend uses `fetch` with a readable response body and a small SSE parser.

### 6.2 UI Layout

The Ask tab keeps the existing question box and answer section.

When a question is running or an answer exists, render:

- **Answer panel**
  - streaming answer text
  - citations when available
  - feedback buttons after final trace id exists

- **Agent Timeline panel**
  - stage list
  - status icon/spinner
  - stage summary
  - elapsed time
  - error message for failed stage

The existing static `Loop Trace`, `Wiki Context`, and `Research Memory` sections remain useful after completion. They can either be kept below the live timeline or folded into the same answer area.

### 6.3 Timeline Stages

Stable frontend stages:

| Stage | Display label | Source events |
|---|---|---|
| `start` | Starting | `start` |
| `intent` | Understanding question | `intent` |
| `rewrite` | Rewriting query | `rewrite` |
| `retrieve` | Retrieving evidence | `retrieved` |
| `reflect` | Reflecting | `reflect` |
| `abstain` | Checking evidence | `abstain` |
| `answer` | Generating answer | `answer_chunk`, `done` |
| `done` | Complete | `done` |
| `error` | Failed | `error` or stream failure |

If a stage is skipped because the current intent or no-evidence path does not need it, the UI omits the stage or marks it `skipped`; it does not mark it as failed.

### 6.4 Error States

Frontend errors must distinguish:

- **Connection error**: the stream could not be opened or disconnected before `done`.
- **Stage error**: backend emitted `error` with a stage.
- **No evidence**: backend emitted `done` with no evidence or abstain no-evidence; this is a valid answer state, not a transport error.
- **Stale event**: ignored because a newer question is active.

User-facing copy is concise and stage-specific:

- `Stream disconnected while generating answer.`
- `Retrieval failed: <message>`
- `No indexed evidence was found for this question.`

### 6.5 Feedback Behavior

Feedback buttons remain disabled until a final `trace_id` exists.

Feedback payload continues to include:

- question
- answer preview
- citations
- answer length
- n_chunks

If a stream ends with an error before trace id is available, feedback is not shown.

## 7. Data Model

No database migration is required.

Frontend state adds:

```ts
type QAStreamStage = {
  stage: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  summary?: string;
  elapsed_ms?: number;
  error?: string;
  details?: Record<string, unknown>;
};
```

The implementation generalizes the existing answer rendering around a `QAResponse`-compatible state object. Streaming events update that state incrementally, and `done` fills the same final fields currently supplied by `QASyncResponse`.

## 8. Testing Plan

### 8.1 Backend Tests

Add or update tests for:

- `qa_stream.stream_answer` emits `start` before expensive stages.
- `intent`, `rewrite`, `retrieved`, `reflect`, `abstain`, `done`, and `error` events include stage/status fields where applicable.
- Error events include the failing stage and message.
- Existing no-evidence stream behavior still ends with `done`.
- Gateway `/api/paper_rag/qa` forwards user id, conversation id, and resolved question as before.

### 8.2 Frontend Tests

Add focused tests if the frontend test harness supports this page:

- `ask()` uses `/api/paper_rag/qa`, not `/api/paper_rag/qa/sync`.
- SSE `answer_chunk` updates visible answer incrementally.
- `retrieved` and `reflect` events update timeline rows.
- `error` event marks the correct stage failed.
- `done` enables feedback when trace id exists.
- A second ask ignores stale events from the first request.

If page-level tests are too heavy, extract the SSE parser and event reducer into pure helpers and test those helpers.

### 8.3 Manual Smoke

Run local backend and frontend, then verify:

1. Ask `What is Self-RAG?`
2. First stage appears within one second after the request starts, assuming the gateway is reachable.
3. Timeline advances through intent, rewrite, retrieve, abstain, answer, and done.
4. Answer text appears incrementally.
5. Citations and feedback appear after completion.
6. Simulated backend error displays the failing stage.
7. Repeated Ask does not mix old and new answer text.

## 9. Acceptance Criteria

V1 is complete when:

- The Paper RAG Ask tab defaults to streaming `/api/paper_rag/qa`.
- The UI no longer waits for `/api/paper_rag/qa/sync` for normal Ask.
- The answer renders incrementally from `answer_chunk` events.
- Agent Timeline shows current stage, completed stages, elapsed time, and errors.
- Backend stream events carry enough normalized data for the timeline.
- Stage-specific errors are visible to users.
- No-evidence completion is shown as a valid outcome, not a generic error.
- Feedback still works after successful completion.
- Existing sync endpoint and tests remain intact.
- Automated tests cover the stream contract and frontend event handling.

## 10. Rollout Plan

1. Implement backend event contract additions behind the existing `/api/paper_rag/qa` endpoint.
2. Add frontend SSE parser and event reducer.
3. Switch Ask to streaming by default.
4. Keep `/api/paper_rag/qa/sync` code path available for fallback/debug.
5. Run backend tests, frontend typecheck/lint, and manual smoke.

## 11. Risks And Mitigations

| Risk | Mitigation |
|---|---|
| SSE POST parsing is brittle | Extract a small parser helper and test chunk boundary cases. |
| Some model calls still take long with no intermediate tokens | Show the current stage as running and emit `start` before model work. |
| Event shape changes break existing tests | Preserve event names and fields; only add fields. |
| Old request events corrupt a newer answer | Track a local request id and ignore stale events. |
| Timeline becomes too noisy | Show concise summaries by default and keep raw details collapsed or omitted. |

## 12. V1 Fixed Decisions

All V1 decisions are intentionally fixed:

- The default Ask path uses SSE.
- The sync endpoint stays as fallback.
- MCP-native streaming is V2.
- Quality tuning is V2.
- No database migration is required.
