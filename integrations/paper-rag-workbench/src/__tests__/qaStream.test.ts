import { describe, expect, test } from "vitest";

import {
  createInitialQaStreamState,
  parseSseMessages,
  reduceQaStreamEvent,
} from "../api/qaStream";

describe("qa stream helpers", () => {
  test("parses SSE messages across chunk boundaries", () => {
    const first = parseSseMessages('event: start\ndata: {"stage":"sta', "");
    expect(first.messages).toEqual([]);
    expect(first.carry).toBe('event: start\ndata: {"stage":"sta');

    const second = parseSseMessages(
      'rt"}\n\nevent: done\ndata: {"answer":"ok"}\n\n',
      first.carry,
    );
    expect(second.carry).toBe("");
    expect(second.messages).toEqual([
      { event: "start", data: { stage: "start" } },
      { event: "done", data: { answer: "ok" } },
    ]);
  });

  test("appends answer chunks and finalizes done data", () => {
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
        chunks: [],
        abstain: { decision: "answer" },
        n_chunks: 1,
        paper_ids: ["p1"],
        query_resolution: { effective_question: "What is Self-RAG?" },
      },
    });

    expect(state.answer.answer).toBe("hello world");
    expect(state.answer.trace_id).toBe("abc");
    expect(state.answer.citations).toEqual(["c1"]);
    expect(state.done).toBe(true);
    expect(state.stages.find((stage) => stage.stage === "answer")?.status).toBe(
      "completed",
    );
  });

  test("marks backend error stage as failed", () => {
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
    expect(state.stages.find((stage) => stage.stage === "retrieve")?.status).toBe(
      "failed",
    );
  });
});
