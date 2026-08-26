# Agent Trace Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Paper RAG QA stream answer tokens and live agent stage progress through the DeerFlow Paper RAG workspace.

**Architecture:** Keep the existing DeerFlow gateway SSE endpoint at `POST /api/paper_rag/qa`, harden the Python `qa_stream` event contract, and switch the Paper RAG Ask tab from blocking `/qa/sync` calls to a fetch-based SSE reader. Put frontend parsing and reducer logic in focused helper files so the large workspace page only wires state into UI.

**Tech Stack:** Python 3.10+ for `paper_rag`, FastAPI + `sse-starlette` for gateway SSE, Next.js/React/TypeScript for DeerFlow frontend, Vitest for frontend pure helper tests, pytest for Python tests.

## Global Constraints

- V1 default Ask path uses streaming `POST /api/paper_rag/qa`.
- Keep `/api/paper_rag/qa/sync` unchanged as fallback and test coverage.
- Keep existing stream event names compatible: `intent`, `rewrite`, `retrieved`, `reflect`, `abstain`, `answer_chunk`, `done`, `error`.
- Add `start` as the first stream event.
- Every stage event includes stable `stage`, `status`, `trace_id`, and concise `summary`; `elapsed_ms` is included when available.
- `answer_chunk` includes `trace_id` and `text`.
- `done` includes `trace_id`, `answer`, `citations`, `abstain`, `n_chunks`, `query_resolution`, and `paper_ids`.
- No database migration.
- No MCP-native streaming in V1.
- No retrieval quality tuning, reranker tuning, chunking changes, or abstain calibration in V1.
- Do not redesign the full Paper RAG workspace page.

---

## File Structure

- Modify `src/paper_rag/rag/qa_stream.py`
  - Owns the canonical stream event contract for the Python QA loop.
  - Generates one stream `trace_id`, emits `start`, and adds `stage/status/elapsed_ms/summary` fields to events.

- Modify `tests/test_finalization.py`
  - Covers pure `qa_stream.stream_answer` event ordering and payload contract.

- Modify `tests/test_gateway_paper_rag.py`
  - Covers DeerFlow gateway SSE pass-through for the new `start` event and normalized payload fields.

- Create `integrations/deer-flow/frontend/src/app/workspace/paper-rag/qa-stream.ts`
  - Owns TypeScript types, SSE POST reader, SSE frame parser, and pure reducer helpers for QA streaming state.

- Create `integrations/deer-flow/frontend/src/app/workspace/paper-rag/agent-timeline.tsx`
  - Owns timeline rendering. Keeps `page.tsx` from growing more UI logic.

- Create `integrations/deer-flow/frontend/tests/unit/paper-rag-qa-stream.test.ts`
  - Covers SSE parser and reducer behavior without a browser page test harness.

- Modify `integrations/deer-flow/frontend/src/app/workspace/paper-rag/page.tsx`
  - Switches Ask from `/qa/sync` to stream helper, renders live answer and Agent Timeline, keeps feedback behavior.

---

### Task 1: Harden Python QA Stream Event Contract

**Files:**
- Modify: `src/paper_rag/rag/qa_stream.py`
- Test: `tests/test_finalization.py`

**Interfaces:**
- Consumes: `paper_rag.observability.new_trace_id() -> str`
- Produces: `stream_answer(...) -> Generator[dict, None, None]` where each yielded dict keeps `{"event": string, "data": dict}`
- Produces event data with common keys: `trace_id: str`, `stage: str`, `status: str`, `summary: str`, `elapsed_ms?: int`

- [ ] **Step 1: Write failing tests for `start` and trace propagation**

Add this test to `tests/test_finalization.py` near the existing streaming tests:

```python
def test_stream_answer_emits_start_with_trace_id(monkeypatch):
    from paper_rag.rag import qa_stream

    monkeypatch.setattr(qa_stream, "_retrieve_round", lambda q, p, k: ([], {"dense_queries": [q], "bm25_query": q}))
    monkeypatch.setattr(qa_stream, "classify", lambda q: {"intent": "factual", "top_k": 5, "max_iter": 1, "rrf_k": 60})

    events = list(qa_stream.stream_answer("Q", paper_ids=None))

    assert events[0]["event"] == "start"
    start = events[0]["data"]
    assert start["stage"] == "start"
    assert start["status"] == "completed"
    assert start["summary"] == "Started Paper RAG QA"
    assert isinstance(start["trace_id"], str)
    assert len(start["trace_id"]) == 16
    trace_id = start["trace_id"]
    assert all(event["data"].get("trace_id") == trace_id for event in events if event["event"] != "error")
```

- [ ] **Step 2: Write failing tests for normalized stage fields**

Add this test below the previous one:

```python
def test_stream_answer_stage_events_include_contract_fields(monkeypatch):
    from paper_rag.rag import qa_stream

    def fake_retrieve(q, p, k):
        return (
            [{
                "chunk_id": "c1",
                "paper_id": "p1",
                "text": "Self-RAG uses retrieval and reflection.",
                "score_rerank": 0.9,
            }],
            {"dense_queries": [q], "bm25_query": q},
        )

    def fake_stream(system, user):
        yield "Self-RAG uses retrieval and reflection. [chunk:c1]"

    monkeypatch.setattr(qa_stream, "_retrieve_round", fake_retrieve)
    monkeypatch.setattr(qa_stream, "classify", lambda q: {"intent": "factual", "top_k": 2, "max_iter": 1, "rrf_k": 60})
    monkeypatch.setattr(qa_stream, "_stream_chat", fake_stream)

    events = list(qa_stream.stream_answer("What is Self-RAG?", paper_ids=None))
    by_name = {event["event"]: event["data"] for event in events if event["event"] != "answer_chunk"}

    assert by_name["intent"]["stage"] == "intent"
    assert by_name["intent"]["status"] == "completed"
    assert isinstance(by_name["intent"]["elapsed_ms"], int)
    assert by_name["rewrite"]["stage"] == "rewrite"
    assert by_name["retrieved"]["stage"] == "retrieve"
    assert by_name["retrieved"]["query"] == "What is Self-RAG?"
    assert by_name["abstain"]["stage"] == "abstain"
    assert by_name["done"]["stage"] == "done"
    assert by_name["done"]["status"] == "completed"
    assert by_name["done"]["trace_id"] == events[0]["data"]["trace_id"]

    chunks = [event for event in events if event["event"] == "answer_chunk"]
    assert chunks
    assert chunks[0]["data"]["stage"] == "answer"
    assert chunks[0]["data"]["trace_id"] == events[0]["data"]["trace_id"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_finalization.py::test_stream_answer_emits_start_with_trace_id tests/test_finalization.py::test_stream_answer_stage_events_include_contract_fields -q
```

Expected: FAIL because `start`, `trace_id`, and normalized stage fields are not emitted yet.

- [ ] **Step 4: Add event helper functions**

In `src/paper_rag/rag/qa_stream.py`, import `perf_counter` and add helpers below `_SYSTEM`:

```python
from time import perf_counter
```

```python
def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _event(
    name: str,
    *,
    trace_id: str,
    stage: str,
    status: str,
    summary: str,
    started: float | None = None,
    **data: Any,
) -> dict:
    payload = {
        "trace_id": trace_id,
        "stage": stage,
        "status": status,
        "summary": summary,
        **data,
    }
    if started is not None:
        payload["elapsed_ms"] = _elapsed_ms(started)
    return {"event": name, "data": payload}
```

- [ ] **Step 5: Generate a stream trace id and emit `start`**

Inside `stream_answer`, before query resolution:

```python
from ..observability import new_trace_id

trace_id = new_trace_id()
yield _event(
    "start",
    trace_id=trace_id,
    stage="start",
    status="completed",
    summary="Started Paper RAG QA",
)
```

- [ ] **Step 6: Wrap stage emissions with timing**

Replace existing direct `yield {"event": ..., "data": ...}` calls with `_event(...)`.

Use this pattern for intent:

```python
stage_started = perf_counter()
intent_cfg = classify(question)
yield _event(
    "intent",
    trace_id=trace_id,
    stage="intent",
    status="completed",
    summary=f"Classified as {intent_cfg['intent']}",
    started=stage_started,
    **intent_cfg,
)
```

Use this pattern for retrieval:

```python
stage_started = perf_counter()
try:
    chunks, rw = _retrieve_round(current_query, paper_ids, top_k)
except Exception as e:
    yield _event(
        "error",
        trace_id=trace_id,
        stage="retrieve",
        status="failed",
        summary="Retrieval failed",
        started=stage_started,
        message=f"retrieve failed: {e}",
    )
    return
```

Use this pattern for `answer_chunk`:

```python
yield {
    "event": "answer_chunk",
    "data": {
        "trace_id": trace_id,
        "stage": "answer",
        "text": tok,
    },
}
```

For `done`, include:

```python
done_data = {
    **done_data,
    "trace_id": trace_id,
    "stage": "done",
    "status": "completed",
    "summary": "Paper RAG QA complete",
}
```

- [ ] **Step 7: Run focused stream tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_finalization.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/paper_rag/rag/qa_stream.py tests/test_finalization.py
git commit -m "feat: normalize paper rag stream events"
```

---

### Task 2: Cover Gateway SSE Contract

**Files:**
- Modify: `tests/test_gateway_paper_rag.py`
- Modify only if required by tests: `integrations/deer-flow/backend/app/gateway/routers/paper_rag.py`

**Interfaces:**
- Consumes: `POST /api/paper_rag/qa`
- Produces: SSE text where event names and JSON data from `qa_stream.stream_answer` pass through unchanged.

- [ ] **Step 1: Add gateway SSE contract test**

Add this test near `test_qa_stream_forwards_user_conversation_and_resolved_question` in `tests/test_gateway_paper_rag.py`:

```python
def test_qa_stream_passes_normalized_stage_events(monkeypatch):
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "alice"

    def fake_stream(question, *, paper_ids=None, conversation_id=None, user_id="system", resolved_question=None):
        yield {
            "event": "start",
            "data": {
                "trace_id": "trace1234567890",
                "stage": "start",
                "status": "completed",
                "summary": "Started Paper RAG QA",
            },
        }
        yield {
            "event": "retrieved",
            "data": {
                "trace_id": "trace1234567890",
                "stage": "retrieve",
                "status": "completed",
                "summary": "Retrieved 2 chunks",
                "elapsed_ms": 7,
                "iter": 0,
                "query": "raw",
                "n_chunks": 2,
            },
        }
        yield {
            "event": "done",
            "data": {
                "trace_id": "trace1234567890",
                "stage": "done",
                "status": "completed",
                "summary": "Paper RAG QA complete",
                "answer": "ok",
                "citations": [],
                "abstain": {},
                "n_chunks": 2,
                "paper_ids": ["p1"],
                "query_resolution": {"effective_question": "raw"},
            },
        }

    monkeypatch.setitem(sys.modules, "paper_rag.rag.qa_stream", type("M", (), {"stream_answer": fake_stream}))

    with TestClient(app).stream("POST", "/api/paper_rag/qa", json={"question": "raw"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: start" in body
    assert '"stage": "retrieve"' in body
    assert '"trace_id": "trace1234567890"' in body
    assert "event: done" in body
```

- [ ] **Step 2: Run test to verify current behavior**

Run:

```bash
PYTHONPATH=src:integrations/deer-flow/backend:integrations/deer-flow/backend/packages/harness python -m pytest tests/test_gateway_paper_rag.py::test_qa_stream_passes_normalized_stage_events -q
```

Expected: PASS if the gateway already passes through normalized events. If it fails due to formatting, continue to Step 3.

- [ ] **Step 3: Preserve JSON payload pass-through if needed**

If the test fails because the router mutates payload fields, update `_gen()` in `integrations/deer-flow/backend/app/gateway/routers/paper_rag.py` so this line remains the only event serialization:

```python
yield {"event": evt["event"], "data": json.dumps(evt["data"], ensure_ascii=False)}
```

Do not rename event names or strip payload keys.

- [ ] **Step 4: Run gateway focused tests**

Run:

```bash
PYTHONPATH=src:integrations/deer-flow/backend:integrations/deer-flow/backend/packages/harness python -m pytest tests/test_gateway_paper_rag.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add tests/test_gateway_paper_rag.py integrations/deer-flow/backend/app/gateway/routers/paper_rag.py
git commit -m "test: cover paper rag stream gateway events"
```

---

### Task 3: Add Frontend SSE Parser And Stream Reducer

**Files:**
- Create: `integrations/deer-flow/frontend/src/app/workspace/paper-rag/qa-stream.ts`
- Create: `integrations/deer-flow/frontend/tests/unit/paper-rag-qa-stream.test.ts`

**Interfaces:**
- Produces: `parseSseMessages(input: string, carry?: string) -> { messages: ParsedSseMessage[]; carry: string }`
- Produces: `createInitialQaStreamState(question: string) -> QAStreamState`
- Produces: `reduceQaStreamEvent(state: QAStreamState, event: QAStreamEvent) -> QAStreamState`
- Produces: `streamPaperQa(options: StreamPaperQaOptions) -> Promise<void>`

- [ ] **Step 1: Write failing parser and reducer tests**

Create `integrations/deer-flow/frontend/tests/unit/paper-rag-qa-stream.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  createInitialQaStreamState,
  parseSseMessages,
  reduceQaStreamEvent,
} from "@/app/workspace/paper-rag/qa-stream";

describe("paper rag qa stream helpers", () => {
  it("parses SSE messages across chunk boundaries", () => {
    const first = parseSseMessages('event: start\\ndata: {"stage":"sta', "");
    expect(first.messages).toEqual([]);
    expect(first.carry).toBe('event: start\\ndata: {"stage":"sta');

    const second = parseSseMessages('rt"}\\n\\nevent: done\\ndata: {"answer":"ok"}\\n\\n', first.carry);
    expect(second.carry).toBe("");
    expect(second.messages).toEqual([
      { event: "start", data: { stage: "start" } },
      { event: "done", data: { answer: "ok" } },
    ]);
  });

  it("appends answer chunks and finalizes done data", () => {
    let state = createInitialQaStreamState("What is Self-RAG?");
    state = reduceQaStreamEvent(state, {
      event: "start",
      data: {
        trace_id: "abc",
        stage: "start",
        status: "completed",
        summary: "Started Paper RAG QA",
      },
    });
    state = reduceQaStreamEvent(state, {
      event: "answer_chunk",
      data: { trace_id: "abc", stage: "answer", text: "hello " },
    });
    state = reduceQaStreamEvent(state, {
      event: "answer_chunk",
      data: { trace_id: "abc", stage: "answer", text: "world" },
    });
    state = reduceQaStreamEvent(state, {
      event: "done",
      data: {
        trace_id: "abc",
        stage: "done",
        status: "completed",
        summary: "Paper RAG QA complete",
        answer: "hello world",
        citations: ["c1"],
        abstain: { decision: "confident" },
        n_chunks: 1,
        paper_ids: ["p1"],
        query_resolution: { effective_question: "What is Self-RAG?" },
      },
    });

    expect(state.answer.answer).toBe("hello world");
    expect(state.answer.trace_id).toBe("abc");
    expect(state.answer.citations).toEqual(["c1"]);
    expect(state.done).toBe(true);
    expect(state.stages.find((stage) => stage.stage === "answer")?.status).toBe("completed");
  });

  it("marks backend error stage as failed", () => {
    const state = reduceQaStreamEvent(createInitialQaStreamState("Q"), {
      event: "error",
      data: {
        trace_id: "abc",
        stage: "retrieve",
        status: "failed",
        summary: "Retrieval failed",
        message: "retrieve failed: boom",
      },
    });

    expect(state.error).toBe("retrieve failed: boom");
    expect(state.stages.find((stage) => stage.stage === "retrieve")?.status).toBe("failed");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd integrations/deer-flow/frontend && corepack pnpm exec vitest run tests/unit/paper-rag-qa-stream.test.ts
```

Expected: FAIL because `qa-stream.ts` does not exist.

- [ ] **Step 3: Create `qa-stream.ts` with types and parser**

Create `integrations/deer-flow/frontend/src/app/workspace/paper-rag/qa-stream.ts`:

```ts
export type QAStreamEventName =
  | "start"
  | "intent"
  | "rewrite"
  | "retrieved"
  | "reflect"
  | "abstain"
  | "answer_chunk"
  | "done"
  | "error";

export type QAStageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export type QAStreamData = {
  trace_id?: string;
  stage?: string;
  status?: QAStageStatus;
  summary?: string;
  elapsed_ms?: number;
  text?: string;
  message?: string;
  answer?: string;
  citations?: string[];
  abstain?: { decision?: string };
  n_chunks?: number;
  paper_ids?: string[];
  query_resolution?: Record<string, unknown>;
  [key: string]: unknown;
};

export type QAStreamEvent = {
  event: QAStreamEventName;
  data: QAStreamData;
};

export type ParsedSseMessage = {
  event: string;
  data: unknown;
};

export function parseSseMessages(input: string, carry = ""): { messages: ParsedSseMessage[]; carry: string } {
  const combined = `${carry}${input}`;
  const parts = combined.split("\\n\\n");
  const nextCarry = parts.pop() ?? "";
  const messages = parts
    .map((part) => {
      const lines = part.split("\\n");
      const event = lines.find((line) => line.startsWith("event: "))?.slice("event: ".length) ?? "message";
      const dataText = lines
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice("data: ".length))
        .join("\\n");
      return { event, data: dataText ? JSON.parse(dataText) : {} };
    })
    .filter((message) => message.event.length > 0);
  return { messages, carry: nextCarry };
}
```

- [ ] **Step 4: Add reducer state and stream reader**

Append the reducer and fetch reader in the same file:

```ts
export type QAStreamStage = {
  stage: string;
  label: string;
  status: QAStageStatus;
  summary?: string;
  elapsed_ms?: number;
  error?: string;
  details?: Record<string, unknown>;
};

export type QAStreamAnswer = {
  answer: string;
  citations: string[];
  abstain: { decision?: string };
  trace_id?: string;
  n_chunks?: number;
  trace?: unknown;
};

export type QAStreamState = {
  question: string;
  answer: QAStreamAnswer;
  stages: QAStreamStage[];
  done: boolean;
  error: string | null;
};

const STAGE_LABELS: Record<string, string> = {
  start: "Starting",
  intent: "Understanding question",
  rewrite: "Rewriting query",
  retrieve: "Retrieving evidence",
  reflect: "Reflecting",
  abstain: "Checking evidence",
  answer: "Generating answer",
  done: "Complete",
};

export function createInitialQaStreamState(question: string): QAStreamState {
  return {
    question,
    answer: { answer: "", citations: [], abstain: {} },
    stages: [],
    done: false,
    error: null,
  };
}

function upsertStage(stages: QAStreamStage[], data: QAStreamData): QAStreamStage[] {
  const stage = String(data.stage ?? "unknown");
  const status = (data.status ?? "completed") as QAStageStatus;
  const item: QAStreamStage = {
    stage,
    label: STAGE_LABELS[stage] ?? stage,
    status,
    summary: data.summary,
    elapsed_ms: typeof data.elapsed_ms === "number" ? data.elapsed_ms : undefined,
    error: typeof data.message === "string" ? data.message : undefined,
    details: data,
  };
  const index = stages.findIndex((existing) => existing.stage === stage);
  if (index === -1) return [...stages, item];
  return stages.map((existing, current) => (current === index ? { ...existing, ...item } : existing));
}

export function reduceQaStreamEvent(state: QAStreamState, event: QAStreamEvent): QAStreamState {
  if (event.event === "answer_chunk") {
    return {
      ...state,
      answer: {
        ...state.answer,
        trace_id: event.data.trace_id ?? state.answer.trace_id,
        answer: `${state.answer.answer}${event.data.text ?? ""}`,
      },
      stages: upsertStage(state.stages, {
        ...event.data,
        stage: "answer",
        status: "running",
        summary: "Generating answer",
      }),
    };
  }
  if (event.event === "done") {
    return {
      ...state,
      done: true,
      answer: {
        answer: String(event.data.answer ?? state.answer.answer),
        citations: Array.isArray(event.data.citations) ? event.data.citations : [],
        abstain: typeof event.data.abstain === "object" && event.data.abstain !== null ? event.data.abstain : {},
        trace_id: event.data.trace_id ?? state.answer.trace_id,
        n_chunks: typeof event.data.n_chunks === "number" ? event.data.n_chunks : undefined,
        trace: { loop: event.data, query_resolution: event.data.query_resolution },
      },
      stages: upsertStage(
        upsertStage(state.stages, { stage: "answer", status: "completed", summary: "Generated answer" }),
        event.data,
      ),
    };
  }
  if (event.event === "error") {
    const message = typeof event.data.message === "string" ? event.data.message : "Stream failed";
    return {
      ...state,
      error: message,
      stages: upsertStage(state.stages, { ...event.data, status: "failed", summary: event.data.summary ?? message }),
    };
  }
  return { ...state, stages: upsertStage(state.stages, event.data) };
}

export type StreamPaperQaOptions = {
  url: string;
  fetcher: typeof fetch;
  body: unknown;
  signal?: AbortSignal;
  onEvent: (event: QAStreamEvent) => void;
};

export async function streamPaperQa({ url, fetcher, body, signal, onEvent }: StreamPaperQaOptions): Promise<void> {
  const response = await fetcher(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let carry = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseSseMessages(decoder.decode(value, { stream: true }), carry);
    carry = parsed.carry;
    for (const message of parsed.messages) {
      onEvent(message as QAStreamEvent);
    }
  }
}
```

- [ ] **Step 5: Run frontend unit tests**

Run:

```bash
cd integrations/deer-flow/frontend && corepack pnpm exec vitest run tests/unit/paper-rag-qa-stream.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add integrations/deer-flow/frontend/src/app/workspace/paper-rag/qa-stream.ts integrations/deer-flow/frontend/tests/unit/paper-rag-qa-stream.test.ts
git commit -m "feat: add paper rag stream reducer"
```

---

### Task 4: Add Agent Timeline Component

**Files:**
- Create: `integrations/deer-flow/frontend/src/app/workspace/paper-rag/agent-timeline.tsx`
- Modify: `integrations/deer-flow/frontend/src/app/workspace/paper-rag/page.tsx`

**Interfaces:**
- Consumes: `QAStreamStage[]` from `qa-stream.ts`
- Produces: `<AgentTimeline stages={stages} running={asking} />`

- [ ] **Step 1: Create Agent Timeline component**

Create `integrations/deer-flow/frontend/src/app/workspace/paper-rag/agent-timeline.tsx`:

```tsx
import { AlertCircleIcon, CheckIcon, Loader2Icon } from "lucide-react";

import { Badge } from "@/components/ui/badge";

import type { QAStreamStage } from "./qa-stream";

type AgentTimelineProps = {
  stages: QAStreamStage[];
  running: boolean;
};

function StageIcon({ stage }: { stage: QAStreamStage }) {
  if (stage.status === "failed") return <AlertCircleIcon className="text-destructive size-4" />;
  if (stage.status === "running") return <Loader2Icon className="text-muted-foreground size-4 animate-spin" />;
  return <CheckIcon className="text-muted-foreground size-4" />;
}

export function AgentTimeline({ stages, running }: AgentTimelineProps) {
  if (!running && stages.length === 0) return null;
  return (
    <div className="space-y-3 rounded-md border bg-muted/20 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">Agent Timeline</h3>
        {running && <Badge variant="secondary">running</Badge>}
      </div>
      <div className="space-y-2">
        {stages.map((stage) => (
          <div key={stage.stage} className="flex gap-2 text-sm">
            <div className="mt-0.5 shrink-0">
              <StageIcon stage={stage} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{stage.label}</span>
                <Badge variant={stage.status === "failed" ? "destructive" : "outline"}>{stage.status}</Badge>
                {typeof stage.elapsed_ms === "number" && <Badge variant="secondary">{stage.elapsed_ms} ms</Badge>}
              </div>
              {stage.summary && <p className="text-muted-foreground mt-1 break-words text-xs">{stage.summary}</p>}
              {stage.error && <p className="text-destructive mt-1 break-words text-xs">{stage.error}</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Import the component in `page.tsx`**

Add imports:

```tsx
import { AgentTimeline } from "./agent-timeline";
import type { QAStreamStage } from "./qa-stream";
```

- [ ] **Step 3: Add temporary page state for typecheck**

Inside `PaperRagPage`, add:

```tsx
const [streamStages, setStreamStages] = useState<QAStreamStage[]>([]);
```

- [ ] **Step 4: Render timeline in the existing answer section**

Inside the answer panel content, before the static `Loop Trace`, add:

```tsx
<AgentTimeline stages={streamStages} running={asking} />
```

- [ ] **Step 5: Run frontend typecheck**

Run:

```bash
cd integrations/deer-flow/frontend && corepack pnpm exec tsc --noEmit
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add integrations/deer-flow/frontend/src/app/workspace/paper-rag/agent-timeline.tsx integrations/deer-flow/frontend/src/app/workspace/paper-rag/page.tsx
git commit -m "feat: add paper rag agent timeline"
```

---

### Task 5: Switch Ask Flow To Streaming

**Files:**
- Modify: `integrations/deer-flow/frontend/src/app/workspace/paper-rag/page.tsx`
- Modify if needed: `integrations/deer-flow/frontend/src/app/workspace/paper-rag/qa-stream.ts`
- Test: `integrations/deer-flow/frontend/tests/unit/paper-rag-qa-stream.test.ts`

**Interfaces:**
- Consumes: `streamPaperQa`, `createInitialQaStreamState`, `reduceQaStreamEvent`
- Produces: Paper RAG Ask UI that calls `/api/paper_rag/qa` and updates answer state from SSE events.

- [ ] **Step 1: Add stale request reducer test**

Extend `paper-rag-qa-stream.test.ts` with this reducer-level behavior:

```ts
it("keeps stream reducer pure for repeated ask resets", () => {
  const first = reduceQaStreamEvent(createInitialQaStreamState("first"), {
    event: "answer_chunk",
    data: { trace_id: "one", stage: "answer", text: "old" },
  });
  const second = createInitialQaStreamState("second");

  expect(first.answer.answer).toBe("old");
  expect(second.answer.answer).toBe("");
  expect(second.question).toBe("second");
});
```

- [ ] **Step 2: Run unit test**

Run:

```bash
cd integrations/deer-flow/frontend && corepack pnpm exec vitest run tests/unit/paper-rag-qa-stream.test.ts
```

Expected: PASS. This test protects the state reset helper used by the page.

- [ ] **Step 3: Update imports and state in `page.tsx`**

Change the React import:

```tsx
import { useEffect, useRef, useState } from "react";
```

Add helper imports:

```tsx
import {
  createInitialQaStreamState,
  reduceQaStreamEvent,
  streamPaperQa,
  type QAStreamEvent,
  type QAStreamState,
  type QAStreamStage,
} from "./qa-stream";
```

Add state and refs in `PaperRagPage`:

```tsx
const [streamState, setStreamState] = useState<QAStreamState | null>(null);
const activeAskIdRef = useRef(0);
const askAbortRef = useRef<AbortController | null>(null);
```

- [ ] **Step 4: Replace sync `ask()` with streaming implementation**

Replace the current `ask()` body with:

```tsx
async function ask() {
  const trimmed = question.trim();
  if (!trimmed) return;
  const askId = activeAskIdRef.current + 1;
  activeAskIdRef.current = askId;
  askAbortRef.current?.abort();
  const controller = new AbortController();
  askAbortRef.current = controller;

  setAsking(true);
  setFeedbackSent(null);
  setMessage(null);
  setError(null);
  setAnswerQuestion(trimmed);
  const initial = createInitialQaStreamState(trimmed);
  setStreamState(initial);
  setAnswer({ answer: "", citations: [], abstain: {} });

  try {
    await streamPaperQa({
      url: `${getBackendBaseURL()}/api/paper_rag/qa`,
      fetcher: fetchWithAuth,
      signal: controller.signal,
      body: { question: trimmed, conversation_id: conversationId },
      onEvent: (event: QAStreamEvent) => {
        if (activeAskIdRef.current !== askId) return;
        setStreamState((current) => {
          const next = reduceQaStreamEvent(current ?? createInitialQaStreamState(trimmed), event);
          setAnswer({
            answer: next.answer.answer,
            citations: next.answer.citations,
            abstain: next.answer.abstain,
            trace_id: next.answer.trace_id,
            n_chunks: next.answer.n_chunks,
            trace: next.answer.trace as QASyncResponse["trace"],
            memory: null,
          });
          return next;
        });
      },
    });
  } catch (err) {
    if (controller.signal.aborted || activeAskIdRef.current !== askId) return;
    const message = err instanceof Error ? err.message : "QA stream failed";
    setError(message);
    setStreamState((current) => ({
      ...(current ?? createInitialQaStreamState(trimmed)),
      error: message,
      stages: [
        ...((current ?? createInitialQaStreamState(trimmed)).stages),
        {
          stage: "error",
          label: "Failed",
          status: "failed",
          summary: "Stream disconnected",
          error: message,
        },
      ],
    }));
  } finally {
    if (activeAskIdRef.current === askId) {
      setAsking(false);
    }
  }
}
```

- [ ] **Step 5: Render streaming answer panel while running**

Change the answer section condition from:

```tsx
{answer && (
```

to:

```tsx
{(answer || streamState) && (
```

Pass timeline stages from stream state:

```tsx
<AgentTimeline stages={streamState?.stages ?? []} running={asking} />
```

Remove the temporary `streamStages` state introduced in Task 4:

```tsx
const [streamStages, setStreamStages] = useState<QAStreamStage[]>([]);
```

- [ ] **Step 6: Keep feedback disabled until final trace id exists**

Keep the existing `answer.trace_id` check around feedback buttons. Confirm that `done` in the reducer sets `answer.trace_id`.

- [ ] **Step 7: Run frontend tests and typecheck**

Run:

```bash
cd integrations/deer-flow/frontend && corepack pnpm exec vitest run tests/unit/paper-rag-qa-stream.test.ts
cd integrations/deer-flow/frontend && corepack pnpm exec tsc --noEmit
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```bash
git add integrations/deer-flow/frontend/src/app/workspace/paper-rag/page.tsx integrations/deer-flow/frontend/src/app/workspace/paper-rag/qa-stream.ts integrations/deer-flow/frontend/tests/unit/paper-rag-qa-stream.test.ts
git commit -m "feat: stream paper rag ask flow"
```

---

### Task 6: Final Verification And Manual Smoke

**Files:**
- Modify only if verification exposes an implementation issue.

**Interfaces:**
- Consumes all prior task outputs.
- Produces verified V1 streaming behavior.

- [ ] **Step 1: Run Python focused tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_finalization.py tests/test_gateway_paper_rag.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend focused tests**

Run:

```bash
cd integrations/deer-flow/frontend && corepack pnpm exec vitest run tests/unit/paper-rag-qa-stream.test.ts
```

Expected: PASS.

- [ ] **Step 3: Run frontend typecheck**

Run:

```bash
cd integrations/deer-flow/frontend && corepack pnpm exec tsc --noEmit
```

Expected: PASS.

- [ ] **Step 4: Run formatting/lint checks for touched areas**

Run:

```bash
ruff check src/paper_rag/rag/qa_stream.py tests/test_finalization.py tests/test_gateway_paper_rag.py
cd integrations/deer-flow/frontend && corepack pnpm exec eslint src/app/workspace/paper-rag tests/unit/paper-rag-qa-stream.test.ts
```

Expected: PASS.

- [ ] **Step 5: Manual smoke backend**

Start backend:

```bash
make deerflow-backend
```

Expected: gateway starts on `http://127.0.0.1:8001`.

- [ ] **Step 6: Manual smoke frontend**

Start frontend in a second terminal:

```bash
make deerflow-frontend
```

Open:

```text
http://127.0.0.1:3000/workspace/paper-rag
```

Ask:

```text
What is Self-RAG?
```

Expected:

- Answer panel appears immediately.
- Agent Timeline shows `Starting`.
- Timeline advances through available stages.
- Answer text appears incrementally when the LLM begins streaming.
- Citations and feedback buttons appear after `done`.
- Asking a second question does not append text from the first request.

- [ ] **Step 7: Commit verification fixes if any**

If Step 1-6 required fixes:

```bash
git add <changed-files>
git commit -m "fix: complete paper rag streaming verification"
```

If no fixes were required, do not create an empty commit.
