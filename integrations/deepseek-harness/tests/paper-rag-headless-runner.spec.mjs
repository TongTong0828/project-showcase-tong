import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test, vi } from "vitest";

import {
  registerIsolatedSmokeApproval,
  run,
  shouldAllowIsolatedSmokeApproval,
  summarize,
} from "../src/paper-rag-headless-runner.mjs";

const integrationRoot = fileURLToPath(new URL("..", import.meta.url));

describe("Paper RAG live headless runner", () => {
  test("live patch replaces the stock headless runner with the Paper RAG preset runner", async () => {
    const patch = await readFile(resolve(integrationRoot, "live-headless.patch.yml"), "utf8");

    expect(patch).toContain("id: headless-runner");
    expect(patch).toContain("disabled: true");
    expect(patch).toContain("id: paper-rag-headless-runner");
    expect(patch).toContain("name: ./src/paper-rag-headless-runner.mjs");
    expect(patch).toContain("preset: paper-research");
    expect(patch).toContain("PAPER_RAG_DSH_HEADLESS_REPORT_JSON");
  });

  test("mounts paper-research before publishing the one-shot agent", async () => {
    const agentCtx = {};
    const session = {
      seq: 1,
      events: [
        { seq: 1, type: "turn/start", data: { turn: 1 } },
        {
          seq: 2,
          type: "assistant/message",
          data: { message: { content: [{ type: "text", text: "done" }] } },
        },
        { seq: 3, type: "turn/end", data: { reason: { kind: "completed" } } },
      ],
    };
    const agent = {
      ctx: agentCtx,
      session,
      followup: vi.fn(),
      whenIdle: vi.fn().mockResolvedValue(undefined),
    };
    const mount = vi.fn().mockResolvedValue({ id: "paper-research" });
    const flush = vi.fn().mockResolvedValue(undefined);
    const create = vi.fn(async (options) => {
      await options.setup(agentCtx);
      return { agent };
    });
    const stdout = { write: vi.fn() };
    const stderr = { write: vi.fn() };
    const exit = vi.fn();
    const ctx = {
      get(name) {
        return {
          agentDefaultModel: {
            currentSelection: () => ({
              provider: "deepseek-official",
              model: "deepseek-v4-flash",
            }),
          },
          agentPresets: { mount },
          agents: { create },
          sessions: { flush },
        }[name];
      },
    };

    await run(ctx, { task: "answer from paper_qa", preset: "paper-research" }, { stdout, stderr, exit });

    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        meta: expect.objectContaining({ agentPreset: "paper-research" }),
        agentOptions: {
          provider: "deepseek-official",
          model: "deepseek-v4-flash",
        },
      }),
    );
    expect(mount).toHaveBeenCalledWith(agentCtx, "paper-research");
    expect(agent.followup).toHaveBeenCalledWith(
      expect.objectContaining({
        content: [{ type: "text", text: "answer from paper_qa" }],
        source: { kind: "user" },
      }),
    );
    expect(flush).toHaveBeenCalledWith(session);
    expect(stdout.write).toHaveBeenCalledWith("done\n");
    expect(stderr.write).not.toHaveBeenCalled();
    expect(exit).toHaveBeenCalledWith(0);
  });

  test("scripted workflow executes Paper RAG native tools through DSH tools runtime", async () => {
    const agentCtx = {};
    const session = { seq: 1, events: [] };
    const agent = {
      id: "agent-scripted",
      ctx: agentCtx,
      session,
      whenIdle: vi.fn().mockResolvedValue(undefined),
    };
    const mount = vi.fn().mockResolvedValue({ id: "paper-research" });
    const flush = vi.fn().mockResolvedValue(undefined);
    const create = vi.fn(async (options) => {
      await options.setup(agentCtx);
      return { agent };
    });
    const execute = vi.fn(async (exec) => scriptedToolResult(exec.name));
    const stdout = { write: vi.fn() };
    const stderr = { write: vi.fn() };
    const exit = vi.fn();
    const emit = vi.fn();
    const ctx = {
      emit,
      get(name) {
        return {
          agentDefaultModel: {
            currentSelection: () => ({
              provider: "deepseek-official",
              model: "deepseek-v4-flash",
            }),
          },
          agentPresets: { mount },
          agents: { create },
          sessions: { flush },
          tools: { execute },
        }[name];
      },
    };

    await run(
      ctx,
      {
        task: "run fixed smoke",
        preset: "paper-research",
        scriptedWorkflow: true,
        includeWorkflow: true,
        reportJson: true,
      },
      { stdout, stderr, exit },
    );

    expect(emit).toHaveBeenCalledWith(
      "agent/inbox/claimed",
      expect.objectContaining({
        agent,
        message: expect.objectContaining({ source: { kind: "user" } }),
      }),
    );
    expect(execute.mock.calls.map(([exec]) => exec.name)).toEqual([
      "paper_discover",
      "discovery_candidate_ingest",
      "paper_qa",
      "paper_deliver",
    ]);
    expect(execute.mock.calls[1][0].arguments).toEqual({ candidate_ids: [11], force: true });
    expect(execute.mock.calls[2][0].arguments.paper_ids).toEqual(["paper-11"]);
    expect(flush).toHaveBeenCalledWith(session);
    const payload = JSON.parse(stdout.write.mock.calls[0][0]);
    expect(payload).toMatchObject({
      preset: "paper-research",
      tool_calls: ["paper_discover", "discovery_candidate_ingest", "paper_qa", "paper_deliver"],
      cards: ["discovery_candidates", "ingest_receipt", "evidence_answer", "artifact_delivery"],
      reason: { kind: "completed" },
    });
    expect(stderr.write).not.toHaveBeenCalled();
    expect(exit).toHaveBeenCalledWith(0);
  });

  test("summarizes Paper RAG tool calls and portable cards from a headless session", () => {
    const events = [
      { seq: 1, type: "turn/start", data: {} },
      {
        seq: 2,
        type: "tool/call",
        data: { name: "paper_discover", arguments: { topic: "agentic rag" } },
      },
      {
        seq: 3,
        type: "tool/result",
        data: {
          name: "paper_discover",
          result: {
            structuredContent: {
              ok: true,
              tool: "paper_discover",
              evidence_role: "discovery_only",
              data: { candidates: [{ id: 11, title: "Candidate" }] },
              warnings: [],
            },
          },
        },
      },
      {
        seq: 4,
        type: "assistant/message",
        data: { message: { content: [{ type: "text", text: "done" }] } },
      },
      { seq: 5, type: "turn/end", data: { reason: { kind: "completed" } } },
    ];

    const summary = summarize(events, 1, { includeWorkflow: true });

    expect(summary.tool_calls).toEqual(["paper_discover"]);
    expect(summary.cards).toEqual(["discovery_candidates"]);
    expect(summary.text).toBe("done");
  });

  test("approves only isolated Paper RAG write tools for live headless smoke", async () => {
    const isolatedEnv = {
      PAPER_RAG_DSH_HEADLESS_APPROVE_WRITES: "isolated",
      PAPER_RAG_CONFIG: "/repo/data/index/migration-gates/live-workspaces/G2/head/config.live-g2.yaml",
      PAPER_RAG_ARTIFACT_ROOT: "/repo/data/index/migration-gates/live-workspaces/G2/head/artifacts",
    };
    const handlers = new Map();
    const ctx = {
      on: vi.fn((event, handler) => {
        handlers.set(event, handler);
        return vi.fn();
      }),
    };

    registerIsolatedSmokeApproval(ctx, isolatedEnv);

    const decide = handlers.get("approval/request");
    expect(ctx.on).toHaveBeenCalledWith("approval/request", expect.any(Function));
    expect(
      shouldAllowIsolatedSmokeApproval(
        { toolName: "paper_deliver", reason: "paper_deliver writes artifact files" },
        isolatedEnv,
      ),
    ).toBe(true);
    await expect(
      decide({ toolName: "paper_deliver", reason: "paper_deliver writes artifact files" }, async () => "unavailable"),
    ).resolves.toBe("allowed-once");
    await expect(
      decide({ toolName: "paper_status" }, async () => "unavailable"),
    ).resolves.toBe("unavailable");
    await expect(
      decide({ toolName: "paper_deliver" }, async () => "unavailable"),
    ).resolves.toBe("unavailable");
    expect(
      shouldAllowIsolatedSmokeApproval(
        { toolName: "paper_deliver", reason: "paper_deliver writes artifact files" },
        { ...isolatedEnv, PAPER_RAG_ARTIFACT_ROOT: "/repo/data/artifacts" },
      ),
    ).toBe(false);
  });
});

function scriptedToolResult(name) {
  const byName = {
    paper_discover: {
      ok: true,
      tool: "paper_discover",
      data: {
        candidates: [{ id: 11, title: "Candidate", paper_id: "paper-11" }],
      },
    },
    discovery_candidate_ingest: {
      ok: true,
      tool: "discovery_candidate_ingest",
      data: {
        results: [{ candidate_id: 11, paper_id: "paper-11", status: "ingested" }],
      },
    },
    paper_qa: {
      ok: true,
      tool: "paper_qa",
      data: {
        citations: ["chunk-1"],
        chunks: [{ chunk_id: "chunk-1", paper_id: "paper-11" }],
      },
    },
    paper_deliver: {
      ok: true,
      tool: "paper_deliver",
      data: {
        artifact: { manifest_path: "/tmp/manifest.json" },
      },
    },
  };
  return {
    isError: false,
    value: {
      structuredContent: byName[name],
    },
    content: [{ type: "text", text: `${name} ok` }],
  };
}
