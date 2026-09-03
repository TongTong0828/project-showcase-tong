import type {
  QaData,
  QaInput,
  QaStageStatus,
  QaStreamData,
  QaStreamEvent,
  QaStreamStage,
  QaStreamState,
} from "../types";

export type ParsedSseMessage = {
  event: string;
  data: unknown;
};

export function parseSseMessages(
  input: string,
  carry = "",
): { messages: ParsedSseMessage[]; carry: string } {
  const combined = `${carry}${input}`;
  const parts = combined.split("\n\n");
  const nextCarry = parts.pop() || "";
  const messages = parts
    .map((part) => {
      const lines = part.split("\n");
      const event =
        lines.find((line) => line.startsWith("event: "))?.slice("event: ".length) ||
        "message";
      const dataText = lines
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice("data: ".length))
        .join("\n");
      return { event, data: dataText ? JSON.parse(dataText) : {} };
    })
    .filter((message) => message.event.length > 0);
  return { messages, carry: nextCarry };
}

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

export function createInitialQaStreamState(question: string): QaStreamState {
  return {
    question,
    answer: { answer: "", citations: [], chunks: [], abstain: {} },
    stages: [],
    done: false,
    error: null,
  };
}

function upsertStage(stages: QaStreamStage[], data: QaStreamData): QaStreamStage[] {
  const stage = String(data.stage || "unknown");
  const status = (data.status || "completed") as QaStageStatus;
  const item: QaStreamStage = {
    stage,
    label: STAGE_LABELS[stage] || stage,
    status,
    summary: data.summary,
    elapsed_ms: typeof data.elapsed_ms === "number" ? data.elapsed_ms : undefined,
    error: typeof data.message === "string" ? data.message : undefined,
  };
  const index = stages.findIndex((existing) => existing.stage === stage);
  if (index === -1) return [...stages, item];
  return stages.map((existing, current) =>
    current === index ? { ...existing, ...item } : existing,
  );
}

export function reduceQaStreamEvent(
  state: QaStreamState,
  event: QaStreamEvent,
): QaStreamState {
  if (event.event === "answer_chunk") {
    return {
      ...state,
      answer: {
        ...state.answer,
        trace_id: event.data.trace_id || state.answer.trace_id,
        answer: `${state.answer.answer}${event.data.text || ""}`,
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
        answer: String(event.data.answer || state.answer.answer),
        citations: Array.isArray(event.data.citations) ? event.data.citations : [],
        chunks: Array.isArray(event.data.chunks) ? event.data.chunks : state.answer.chunks,
        abstain: (event.data.abstain || state.answer.abstain) as QaData["abstain"],
        note_refs: Array.isArray(event.data.note_refs)
          ? event.data.note_refs.map(String)
          : state.answer.note_refs,
        context_policy:
          typeof event.data.context_policy === "object" && event.data.context_policy !== null
            ? (event.data.context_policy as QaData["context_policy"])
            : state.answer.context_policy,
        project_context_warnings: Array.isArray(event.data.project_context_warnings)
          ? event.data.project_context_warnings.map(String)
          : state.answer.project_context_warnings,
        trace_id: event.data.trace_id || state.answer.trace_id,
        n_chunks: typeof event.data.n_chunks === "number" ? event.data.n_chunks : undefined,
      },
      stages: upsertStage(
        upsertStage(state.stages, {
          stage: "answer",
          status: "completed",
          summary: "Generated answer",
        }),
        event.data,
      ),
    };
  }
  if (event.event === "error") {
    const message = typeof event.data.message === "string" ? event.data.message : "Stream failed";
    return {
      ...state,
      error: message,
      stages: upsertStage(state.stages, {
        ...event.data,
        status: "failed",
        summary: event.data.summary || message,
      }),
    };
  }
  return { ...state, stages: upsertStage(state.stages, event.data) };
}

export type StreamPaperQaOptions = {
  url: string;
  fetcher: typeof fetch;
  body: QaInput;
  signal?: AbortSignal;
  onEvent: (event: QaStreamEvent) => void;
};

export async function streamPaperQa({
  url,
  fetcher,
  body,
  signal,
  onEvent,
}: StreamPaperQaOptions): Promise<void> {
  const response = await fetcher(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`QA stream failed with ${response.status}`);
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
      onEvent(message as QaStreamEvent);
    }
  }
  if (carry) {
    const parsed = parseSseMessages("\n\n", carry);
    for (const message of parsed.messages) {
      onEvent(message as QaStreamEvent);
    }
  }
}
