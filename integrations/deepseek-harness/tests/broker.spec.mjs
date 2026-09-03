import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, test, vi } from "vitest";

import {
  INHERITED_GLOBAL_ALLOW,
  PaperRagBrokerGenerationHost,
  PaperRagNativeBroker,
  buildPaperRagMcpChildEnv,
  createBrokerExec,
  deriveRequestBoundaryId,
  mcpRequestOptionsForTool,
  redactSecrets,
  registerPaperRagNativeTools,
  toolSchemaHash,
} from "../src/broker.mjs";
import {
  DEFAULT_MCP_ARGS,
  credentialProviderForContext,
  paperRagApprovalService,
  registerPaperRagRequestBoundaryTracking,
  shouldAllowIsolatedBrokerApproval,
} from "../src/paper-rag-native-broker-plugin.mjs";
import { pathsFor } from "../src/paths.mjs";

const paths = pathsFor();
const fixtureCommand = process.execPath;
const fixtureArgs = [new URL("../fixtures/private-mcp-server.mjs", import.meta.url).pathname];
const pythonFixtureCommand = join(paths.repoRoot, ".venv/bin/python");
const pythonFixtureArgs = [
  new URL("../fixtures/private_mcp_server.py", import.meta.url).pathname,
];
const cleanup = [];
const MODEL_TOOL_NAMES = [
  "discovery_candidate_ingest",
  "discovery_run_get",
  "paper_compare",
  "paper_deliver",
  "paper_discover",
  "paper_ingest",
  "paper_list",
  "paper_qa",
  "paper_search",
  "paper_section",
  "paper_status",
  "wiki_lookup",
];
const FINAL_G1_CATALOG_NAMES = [
  "skill",
  "ask_user_question",
  "paper_status",
  "paper_list",
  "paper_search",
  "paper_qa",
  "paper_section",
  "paper_compare",
  "wiki_lookup",
  "paper_discover",
  "discovery_run_get",
  "paper_ingest",
  "discovery_candidate_ingest",
  "paper_deliver",
];

afterEach(async () => {
  while (cleanup.length > 0) {
    await cleanup.pop()();
  }
});

/** @param {string | (() => string)} [value] */
function credentials(value = "g0-secret-token") {
  const currentValue = () => (typeof value === "function" ? value() : value);
  return {
    async describe(ref) {
      return { configured: ref === "PAPER_RAG_TEST_TOKEN", writable: false, source: "test" };
    },
    async resolve(ref) {
      return ref === "PAPER_RAG_TEST_TOKEN" ? { value: currentValue(), source: "test" } : undefined;
    },
  };
}

function namedCredentials(values = {}) {
  return {
    async describe(ref) {
      return {
        configured: typeof values[ref] === "string" && values[ref].length > 0,
        writable: false,
        source: "test",
      };
    },
    async resolve(ref) {
      const value = values[ref];
      return typeof value === "string" && value.length > 0
        ? { value, source: "test" }
        : undefined;
    },
  };
}

function approval(outcome = "allowed-once", calls = []) {
  return {
    async request(req) {
      calls.push(req);
      return outcome;
    },
  };
}

function cancellableApproval(calls = []) {
  return {
    request(req) {
      calls.push(req);
      return new Promise((_resolve, reject) => {
        req.signal?.addEventListener("abort", () => reject(new Error("cancelled")), {
          once: true,
        });
      });
    },
  };
}

function createTestBroker(options = {}) {
  return new PaperRagNativeBroker({
    command: options.command ?? fixtureCommand,
    args: options.args ?? fixtureArgs,
    cwd: paths.integrationRoot,
    credentials: options.credentials ?? credentials(),
    credentialRefs: Object.hasOwn(options, "credentialRefs")
      ? options.credentialRefs
      : ["PAPER_RAG_TEST_TOKEN"],
    childEnv: options.childEnv ?? {},
    activePresetId: options.activePresetId ?? "paper-research",
    approval: Object.hasOwn(options, "approval") ? options.approval : approval(),
    includeWriteProbe: options.includeWriteProbe ?? false,
  });
}

async function startBroker(options = {}) {
  const broker = createTestBroker(options);
  cleanup.push(() => broker.close());
  await broker.activate();
  return broker;
}

async function newAuditPath() {
  const dir = await mkdtemp(join(tmpdir(), "paper-rag-broker-"));
  cleanup.push(() => rm(dir, { recursive: true, force: true }));
  return join(dir, "audit.jsonl");
}

async function readAuditLines(path) {
  return (await readFile(path, "utf8"))
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function establishBoundary(broker, exec, ids = ["msg-user"]) {
  return broker.updateRequestBoundary(
    exec.agent,
    ids.map((id) => ({ id, source: { kind: "user" } })),
  );
}

function delay(ms) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

describe("PaperRagNativeBroker private MCP boundary", () => {
  test("discovers raw MCP tools but exposes only broker-owned native names", async () => {
    const broker = await startBroker();

    expect(broker.rawToolNames()).toContain("paper_status");
    expect(broker.rawToolNames()).toContain("write_probe");
    expect(broker.modelCatalog().map((tool) => tool.name).sort()).toEqual(
      MODEL_TOOL_NAMES,
    );
    expect(broker.modelCatalog().some((tool) => tool.name.startsWith("mcp__"))).toBe(false);
    expect(broker.modelCatalog().some((tool) => tool.name === "write_probe")).toBe(false);
    expect(broker.modelCatalog().some((tool) => tool.name === "wiki_generate")).toBe(false);
    expect(broker.modelCatalog().some((tool) => tool.name === "export_bibtex")).toBe(false);
  });

  test("registers broker-owned native tools through the DSH tool registry", () => {
    const broker = createTestBroker();
    const registered = [];
    const disposers = [];
    const ctx = {
      tools: {
        register(definition) {
          const dispose = vi.fn();
          registered.push(definition);
          disposers.push(dispose);
          return dispose;
        },
      },
    };

    const dispose = registerPaperRagNativeTools(ctx, broker);

    expect(registered.map((tool) => tool.name).sort()).toEqual(MODEL_TOOL_NAMES);
    expect(registered.some((tool) => tool.name.startsWith("mcp__"))).toBe(false);
    expect(registered.every((tool) => typeof tool.execute === "function")).toBe(true);

    dispose();
    expect(disposers.map((fn) => fn.mock.calls.length)).toEqual(
      Array.from({ length: MODEL_TOOL_NAMES.length }, () => 1),
    );
  });

  test("builds an explicit MCP child env without inheriting API keys", () => {
    const env = buildPaperRagMcpChildEnv({
      repoRoot: "/repo",
      artifactRoot: "/repo/data/artifacts",
      importRoot: "/repo/data/imports",
      sourceEnv: {
        OPENAI_API_KEY: "sk-secret",
        RANDOM_SERVICE_TOKEN: "secret-token",
        OPENAI_BASE_URL: "https://api.deepseek.com",
        CHAT_MODEL: "deepseek-v4-flash",
        SMALL_MODEL: "deepseek-v4-flash",
        PAPER_RAG_CONFIG: "/repo/data/index/migration-gates/live-workspaces/G2/head/config.live-g2.yaml",
        FEEDBACK_SQLITE_PATH: "/repo/data/index/migration-gates/live-workspaces/G2/head/data/index/feedback.sqlite",
        PATH: "/usr/bin",
        HOME: "/tmp/home",
      },
    });

    expect(env.OPENAI_API_KEY).toBeUndefined();
    expect(env.RANDOM_SERVICE_TOKEN).toBeUndefined();
    expect(env.OPENAI_BASE_URL).toBe("https://api.deepseek.com");
    expect(env.CHAT_MODEL).toBe("deepseek-v4-flash");
    expect(env.SMALL_MODEL).toBe("deepseek-v4-flash");
    expect(env.PAPER_RAG_CONFIG).toBe(
      "/repo/data/index/migration-gates/live-workspaces/G2/head/config.live-g2.yaml",
    );
    expect(env.FEEDBACK_SQLITE_PATH).toBe(
      "/repo/data/index/migration-gates/live-workspaces/G2/head/data/index/feedback.sqlite",
    );
    expect(env.PYTHONPATH).toBe("/repo/src");
    expect(env.PAPER_RAG_MCP_TOOLSET).toBe("readonly");
    expect(env.PAPER_RAG_ARTIFACT_ROOT).toBe("/repo/data/artifacts");
    expect(env.PAPER_RAG_IMPORT_ROOT).toBe("/repo/data/imports");
  });

  test("defaults the private Python child to the package MCP stdio entrypoint", () => {
    expect(DEFAULT_MCP_ARGS).toEqual(["-m", "paper_rag.mcp"]);
  });

  test("uses the DSH credentials service when the host context provides it", () => {
    const service = namedCredentials({ OPENAI_API_KEY: "dsh-secret" });
    const ctx = {
      get(name) {
        return name === "credentials" ? service : undefined;
      },
    };

    expect(credentialProviderForContext(ctx)).toBe(service);
  });

  test("uses ctx.credentials when Cordis injects the credential service directly", () => {
    const service = namedCredentials({ DEEPSEEK_API_KEY: "dsh-secret" });
    const ctx = { credentials: service };

    expect(credentialProviderForContext(ctx)).toBe(service);
  });

  test("allows only isolated live smoke writes without DSH turn-scoped approval", async () => {
    const isolatedEnv = {
      PAPER_RAG_DSH_HEADLESS_APPROVE_WRITES: "isolated",
      PAPER_RAG_CONFIG: "/repo/data/index/migration-gates/live-workspaces/G2/head/config.live-g2.yaml",
      PAPER_RAG_ARTIFACT_ROOT: "/repo/data/index/migration-gates/live-workspaces/G2/head/artifacts",
    };
    const delegated = [];
    const service = paperRagApprovalService(approval("denied", delegated), isolatedEnv);

    expect(
      shouldAllowIsolatedBrokerApproval(
        {
          toolName: "discovery_candidate_ingest",
          reason: "discovery_candidate_ingest writes approved candidates",
        },
        isolatedEnv,
      ),
    ).toBe(true);
    await expect(
      service.request({
        toolName: "discovery_candidate_ingest",
        reason: "discovery_candidate_ingest writes approved candidates",
      }),
    ).resolves.toBe("allowed-once");
    await expect(
      service.request({ toolName: "paper_status", reason: "paper_status read" }),
    ).resolves.toBe("denied");
    expect(delegated).toHaveLength(1);
    expect(
      shouldAllowIsolatedBrokerApproval(
        {
          toolName: "paper_deliver",
          reason: "paper_deliver writes artifact files",
        },
        { ...isolatedEnv, PAPER_RAG_ARTIFACT_ROOT: "/repo/data/artifacts" },
      ),
    ).toBe(false);
  });

  test("uses explicit MCP request timeouts for slow Paper RAG tools", () => {
    const signal = new AbortController().signal;

    expect(mcpRequestOptionsForTool("paper_discover", signal)).toMatchObject({
      signal,
      timeout: expect.any(Number),
      resetTimeoutOnProgress: true,
    });
    expect(mcpRequestOptionsForTool("paper_discover", signal).timeout).toBeGreaterThan(60_000);
    expect(mcpRequestOptionsForTool("discovery_candidate_ingest", signal).timeout).toBeGreaterThan(
      mcpRequestOptionsForTool("paper_status", signal).timeout,
    );
    expect(mcpRequestOptionsForTool("paper_deliver", signal).timeout).toBeGreaterThan(60_000);
  });

  test("renders bounded model text from the canonical private MCP result", async () => {
    const broker = await startBroker();
    const args = { question: "projection check" };
    const result = await broker.execute(
      "paper_status",
      args,
      createBrokerExec({ agentId: "agent-render", callId: "call-render" }),
    );

    const content = broker.renderForModel("paper_status", args, result);

    expect(content).toHaveLength(1);
    expect(content[0]).toMatchObject({ type: "text" });
    const text = content[0].type === "text" ? content[0].text : "";
    expect(text).toContain("ok");
    expect(text.length).toBeLessThan(1024);
  });

  test("sends hidden paper_rag metadata through tools/call params _meta, not model arguments", async () => {
    const auditPath = await newAuditPath();
    const broker = await startBroker({
      childEnv: { PAPER_RAG_PRIVATE_AUDIT_PATH: auditPath },
    });

    const result = await broker.execute(
      "paper_status",
      { question: "indexed corpus status?" },
      createBrokerExec({ agentId: "agent-123", sessionId: "session-456", callId: "call-789" }),
    );

    expect(result.structuredContent.received_arguments).toEqual({
      question: "indexed corpus status?",
    });
    expect(result.structuredContent.received_meta).toEqual({});
    expect(JSON.stringify(result)).not.toContain("conversation_id");
    expect(JSON.stringify(result.structuredContent.received_arguments)).not.toContain(
      "conversation_id",
    );

    const [audit] = await readAuditLines(auditPath);
    expect(audit.received_arguments).toEqual({
      question: "indexed corpus status?",
    });
    expect(audit.received_meta.paper_rag).toMatchObject({
      conversation_id: "agent-123",
      actor_id: "system",
      caller: "deepseek_harness",
      tool_call_id: "call-789",
    });
  });

  test("sends hidden paper_rag metadata to a Python stdio MCP receiver", async () => {
    const auditPath = await newAuditPath();
    const broker = await startBroker({
      command: pythonFixtureCommand,
      args: pythonFixtureArgs,
      childEnv: { PAPER_RAG_PRIVATE_AUDIT_PATH: auditPath },
    });

    const result = await broker.execute(
      "paper_status",
      { question: "python wire check" },
      createBrokerExec({ agentId: "agent-python", callId: "call-python" }),
    );

    expect(result.structuredContent.received_arguments).toEqual({
      question: "python wire check",
    });
    expect(JSON.stringify(result)).not.toContain("agent-python");
    const [audit] = await readAuditLines(auditPath);
    expect(audit.receiver).toBe("python");
    expect(audit.received_meta.paper_rag).toMatchObject({
      conversation_id: "agent-python",
      caller: "deepseek_harness",
      tool_call_id: "call-python",
    });
  });

  test("derives request boundary from the claimed direct-user message batch", async () => {
    const broker = await startBroker();
    const exec = createBrokerExec({
      agentId: "agent-boundary",
      sessionId: "session-boundary",
      callId: "call-boundary",
    });

    const boundary = broker.updateRequestBoundary(exec.agent, [
      { id: "user-1", source: { kind: "user" } },
      { id: "user-2", source: { kind: "user" } },
    ]);

    expect(boundary).toBe(deriveRequestBoundaryId("session-boundary", ["user-1", "user-2"]));
    expect(
      broker.updateRequestBoundary(exec.agent, [
        { id: "synthetic-1", source: { kind: "skill" } },
        { id: "synthetic-2", source: { kind: "goal" } },
      ]),
    ).toBe(boundary);

    const steeringBoundary = broker.updateRequestBoundary(exec.agent, [
      { id: "user-steering", source: { kind: "user" } },
    ]);
    expect(steeringBoundary).toBe(
      deriveRequestBoundaryId("session-boundary", ["user-steering"]),
    );
    expect(steeringBoundary).not.toBe(boundary);
  });

  test("resume without a new direct-user message denies writes before approval", async () => {
    const approvalCalls = [];
    const broker = await startBroker({
      approval: approval("allowed-once", approvalCalls),
      includeWriteProbe: true,
    });
    const exec = createBrokerExec({ agentId: "agent-resume", callId: "call-resume" });

    const read = await broker.execute(
      "paper_status",
      { question: "read after resume" },
      exec,
    );
    expect(read.structuredContent.ok).toBe(true);

    await expect(broker.execute("write_probe", { note: "resume write" }, exec)).rejects.toThrow(
      "DIRECT_USER_AUTHORITY_REQUIRED",
    );
    expect(approvalCalls).toHaveLength(0);
    const status = await broker.execute(
      "paper_status",
      { question: "write count" },
      createBrokerExec({ agentId: "agent-resume", callId: "call-resume-status" }),
    );
    expect(status.structuredContent.write_call_count).toBe(0);
  });

  test("approval-gated Paper RAG writes require a direct user boundary", async () => {
    const approvalCalls = [];
    const broker = await startBroker({
      approval: approval("allowed-once", approvalCalls),
    });
    const exec = createBrokerExec({
      agentId: "agent-write-denied",
      callId: "call-write-denied",
    });

    await expect(
      broker.execute("paper_ingest", { arxiv_id: "2601.00001" }, exec),
    ).rejects.toThrow("DIRECT_USER_AUTHORITY_REQUIRED");
    expect(approvalCalls).toHaveLength(0);
  });

  test("approval-gated Paper RAG writes send side-effect reason and hidden boundary", async () => {
    const approvalCalls = [];
    const auditPath = await newAuditPath();
    const broker = await startBroker({
      childEnv: { PAPER_RAG_PRIVATE_AUDIT_PATH: auditPath },
      approval: approval("allowed-once", approvalCalls),
    });
    const exec = createBrokerExec({
      agentId: "agent-write-ok",
      sessionId: "session-write-ok",
      callId: "call-write-ok",
    });
    const boundary = establishBoundary(broker, exec, ["user-write"]);

    const result = await broker.execute(
      "discovery_candidate_ingest",
      { candidate_ids: [11], force: true },
      exec,
    );

    expect(result.structuredContent.ok).toBe(true);
    expect(approvalCalls).toHaveLength(1);
    expect(approvalCalls[0].toolName).toBe("discovery_candidate_ingest");
    expect(approvalCalls[0].reason).toContain("candidate_ids=11");
    expect(JSON.stringify(result)).not.toContain(boundary);
    const audit = (await readAuditLines(auditPath)).find(
      (line) => line.tool_name === "discovery_candidate_ingest",
    );
    expect(audit.received_meta.paper_rag.request_boundary_id).toBe(boundary);
  });

  test("request boundary rides hidden metadata and stays out of arguments and results", async () => {
    const auditPath = await newAuditPath();
    const broker = await startBroker({
      childEnv: { PAPER_RAG_PRIVATE_AUDIT_PATH: auditPath },
      includeWriteProbe: true,
    });
    const exec = createBrokerExec({
      agentId: "agent-boundary-wire",
      sessionId: "session-boundary-wire",
      callId: "call-boundary-wire",
    });
    const boundary = establishBoundary(broker, exec, ["user-wire-1", "user-wire-2"]);

    const result = await broker.execute("write_probe", { note: "hidden boundary" }, exec);

    expect(result.structuredContent.received_arguments).toEqual({ note: "hidden boundary" });
    expect(JSON.stringify(result)).not.toContain(boundary);
    expect(JSON.stringify(result.structuredContent.received_arguments)).not.toContain(
      "request_boundary_id",
    );
    const audit = (await readAuditLines(auditPath)).find(
      (line) => line.tool_name === "write_probe",
    );
    expect(audit.received_meta.paper_rag.request_boundary_id).toBe(boundary);
  });

  test("tracks claimed direct user messages as the active write boundary", () => {
    const broker = createTestBroker();
    const handlers = new Map();
    const ctx = {
      on: vi.fn((event, handler) => {
        handlers.set(event, handler);
        return vi.fn();
      }),
    };
    const exec = createBrokerExec({
      agentId: "agent-claimed-boundary",
      sessionId: "session-claimed-boundary",
    });

    registerPaperRagRequestBoundaryTracking(ctx, broker);

    handlers.get("agent/inbox/claimed")({
      agent: exec.agent,
      message: { id: "user-claimed", source: { kind: "user" }, content: [] },
      turn: 1,
    });
    handlers.get("agent/inbox/claimed")({
      agent: exec.agent,
      message: { id: "plugin-context", source: { kind: "plugin", plugin: "x" }, content: [] },
      turn: 1,
    });

    expect(ctx.on).toHaveBeenCalledWith("agent/inbox/claimed", expect.any(Function));
    expect(broker.currentRequestBoundaryId(exec.agent)).toBe(
      deriveRequestBoundaryId("session-claimed-boundary", ["user-claimed"]),
    );
  });

  test("private MCP child crash is diagnosable and restart restores tool calls", async () => {
    const broker = await startBroker();
    const originalPid = broker.privateMcpPid();
    expect(originalPid).toEqual(expect.any(Number));

    process.kill(originalPid, "SIGTERM");
    await delay(50);

    await expect(
      broker.execute(
        "paper_status",
        { question: "after crash" },
        createBrokerExec({ agentId: "agent-crash", callId: "call-crash" }),
      ),
    ).rejects.toThrow();

    await broker.restart();
    const restartedPid = broker.privateMcpPid();
    expect(restartedPid).toEqual(expect.any(Number));
    expect(restartedPid).not.toBe(originalPid);
    const recovered = await broker.execute(
      "paper_status",
      { question: "after restart" },
      createBrokerExec({ agentId: "agent-crash", callId: "call-restart" }),
    );
    expect(recovered.structuredContent.ok).toBe(true);
  });

  test("cancels an in-flight private MCP call and keeps the child usable", async () => {
    const auditPath = await newAuditPath();
    const broker = await startBroker({
      childEnv: { PAPER_RAG_PRIVATE_AUDIT_PATH: auditPath },
    });
    const controller = new AbortController();
    const pending = broker.execute(
      "paper_status",
      { question: "slow-cancel" },
      createBrokerExec({
        agentId: "agent-cancel-mcp",
        callId: "call-cancel-mcp",
        signal: controller.signal,
      }),
    );

    await delay(25);
    controller.abort(new Error("cancelled by test"));

    await expect(pending).rejects.toThrow("cancelled by test");
    await delay(25);
    const audit = await readAuditLines(auditPath);
    expect(audit.some((line) => line.lifecycle === "cancelled")).toBe(true);

    const recovered = await broker.execute(
      "paper_status",
      { question: "after cancel" },
      createBrokerExec({ agentId: "agent-cancel-mcp", callId: "call-after-cancel" }),
    );
    expect(recovered.structuredContent.ok).toBe(true);
  });

  test("standing broker generation serves multiple agents with isolated boundaries", async () => {
    const broker = await startBroker();
    const sharedPid = broker.privateMcpPid();
    const agentA = createBrokerExec({
      agentId: "agent-a",
      sessionId: "session-a",
      callId: "call-a",
    });
    const agentB = createBrokerExec({
      agentId: "agent-b",
      sessionId: "session-b",
      callId: "call-b",
    });

    const boundaryA = establishBoundary(broker, agentA, ["user-a"]);
    const boundaryB = establishBoundary(broker, agentB, ["user-b"]);

    expect(boundaryA).not.toBe(boundaryB);
    expect(broker.currentRequestBoundaryId(agentA.agent)).toBe(boundaryA);
    expect(broker.currentRequestBoundaryId(agentB.agent)).toBe(boundaryB);
    expect(broker.privateMcpPid()).toBe(sharedPid);
    await expect(
      broker.execute("paper_status", { question: "agent a" }, agentA),
    ).resolves.toMatchObject({ structuredContent: { ok: true } });
    await expect(
      broker.execute("paper_status", { question: "agent b" }, agentB),
    ).resolves.toMatchObject({ structuredContent: { ok: true } });
    expect(broker.privateMcpPid()).toBe(sharedPid);
  });

  test("standing generation host retains old children until bounded shutdown", async () => {
    const host = new PaperRagBrokerGenerationHost({
      brokerFactory: () => createTestBroker(),
    });
    cleanup.push(() => host.shutdown());

    const agentA = await host.acquire("generation-1", "agent-a");
    const agentB = await host.acquire("generation-1", "agent-b");
    const firstPid = agentA.broker.privateMcpPid();
    expect(firstPid).toBeTypeOf("number");
    expect(agentB.broker).toBe(agentA.broker);
    expect(agentB.broker.privateMcpPid()).toBe(firstPid);

    await agentA.release();
    expect(host.diagnostics()).toMatchObject({
      generation_count: 1,
      live_private_mcp_pids: [firstPid],
    });
    await expect(
      agentB.broker.execute(
        "paper_status",
        { question: "agent b after a release" },
        createBrokerExec({ agentId: "agent-b", callId: "call-b-after-release" }),
      ),
    ).resolves.toMatchObject({ structuredContent: { ok: true } });

    const agentC = await host.acquire("generation-2", "agent-c");
    const secondPid = agentC.broker.privateMcpPid();
    expect(secondPid).toBeTypeOf("number");
    expect(secondPid).not.toBe(firstPid);
    expect(host.diagnostics()).toMatchObject({
      generation_count: 2,
      retained_generation_count: 2,
    });

    await agentB.release();
    await agentC.release();
    expect(host.diagnostics()).toMatchObject({
      generation_count: 2,
      retained_generation_count: 2,
    });

    await host.shutdown();
    expect(host.diagnostics()).toMatchObject({
      generation_count: 0,
      live_private_mcp_pids: [],
    });
  });

  test("passes credentials only as explicit child env and redacts secret-shaped evidence", async () => {
    const broker = await startBroker({ credentials: credentials("rotate-me-secret") });

    const result = await broker.execute(
      "paper_status",
      { question: "credential check" },
      createBrokerExec({ agentId: "agent-cred", callId: "call-cred" }),
    );

    expect(result.structuredContent.has_test_credential).toBe(true);
    expect(JSON.stringify(result)).not.toContain("rotate-me-secret");
    expect(redactSecrets("token=rotate-me-secret", ["rotate-me-secret"])).toBe(
      "token=[REDACTED]",
    );
  });

  test("aliases DeepSeek credentials into the OpenAI-compatible Paper RAG env", async () => {
    const broker = await startBroker({
      command: pythonFixtureCommand,
      args: pythonFixtureArgs,
      credentials: namedCredentials({ DEEPSEEK_API_KEY: "deepseek-secret" }),
      credentialRefs: ["DEEPSEEK_API_KEY"],
      childEnv: {
        OPENAI_BASE_URL: "https://api.deepseek.com",
        CHAT_MODEL: "deepseek-v4-flash",
      },
    });

    const result = await broker.execute(
      "paper_status",
      { question: "deepseek alias check" },
      createBrokerExec({ agentId: "agent-alias", callId: "call-alias" }),
    );

    expect(result.structuredContent.has_openai_credential).toBe(true);
    expect(JSON.stringify(result)).not.toContain("deepseek-secret");
  });

  test("does not inherit parent credential env without an explicit credential ref", async () => {
    const previous = process.env.PAPER_RAG_TEST_TOKEN;
    process.env.PAPER_RAG_TEST_TOKEN = "parent-only-test-token";
    try {
      const broker = await startBroker({ credentialRefs: [] });

      const result = await broker.execute(
        "paper_status",
        { question: "parent env check" },
        createBrokerExec({ agentId: "agent-parent", callId: "call-parent" }),
      );

      expect(result.structuredContent.has_test_credential).toBe(false);
      expect(result.structuredContent.credential_generation).toBe("absent");
      expect(JSON.stringify(result)).not.toContain("parent-only-test-token");
    } finally {
      if (previous === undefined) {
        delete process.env.PAPER_RAG_TEST_TOKEN;
      } else {
        process.env.PAPER_RAG_TEST_TOKEN = previous;
      }
    }
  });

  test("rotates credentials by restarting a private child generation", async () => {
    let currentCredential = "initial-test-token";
    const broker = await startBroker({ credentials: credentials(() => currentCredential) });

    const initial = await broker.execute(
      "paper_status",
      { question: "initial credential" },
      createBrokerExec({ agentId: "agent-rotate", callId: "call-rotate-1" }),
    );
    expect(initial.structuredContent.credential_generation).toBe("initial");

    currentCredential = "rotated-test-token";
    await broker.restart();
    const rotated = await broker.execute(
      "paper_status",
      { question: "rotated credential" },
      createBrokerExec({ agentId: "agent-rotate", callId: "call-rotate-2" }),
    );

    expect(rotated.structuredContent.credential_generation).toBe("rotated");
    expect(JSON.stringify(rotated)).not.toContain("rotated-test-token");
  });

  test("write tools request one-shot approval with the real exec signal before MCP call", async () => {
    const approvalCalls = [];
    const broker = await startBroker({
      approval: approval("allowed-once", approvalCalls),
      includeWriteProbe: true,
    });
    const exec = createBrokerExec({
      agentId: "agent-write",
      sessionId: "session-write",
      callId: "call-write",
    });
    establishBoundary(broker, exec);

    const result = await broker.execute("write_probe", { note: "ok" }, exec);

    expect(approvalCalls).toHaveLength(1);
    expect(approvalCalls[0]).toMatchObject({
      agent: exec.agent,
      toolName: "write_probe",
      callId: "call-write",
    });
    expect(approvalCalls[0].signal).toBe(exec.signal);
    expect(result.structuredContent.approved).toBe(true);
  });

  test("write tools do not call private MCP when approval is rejected", async () => {
    const broker = await startBroker({ approval: approval("rejected"), includeWriteProbe: true });
    const exec = createBrokerExec({ agentId: "agent-reject", callId: "call-reject" });
    establishBoundary(broker, exec);

    await expect(
      broker.execute("write_probe", { note: "deny" }, exec),
    ).rejects.toThrow("approval rejected");

    const status = await broker.execute(
      "paper_status",
      { question: "write count" },
      createBrokerExec({ agentId: "agent-reject", callId: "call-reject-status" }),
    );
    expect(status.structuredContent.write_call_count).toBe(0);
  });

  test("write tools fail closed when approval is unavailable", async () => {
    const broker = await startBroker({
      approval: approval("unavailable"),
      includeWriteProbe: true,
    });
    const exec = createBrokerExec({ agentId: "agent-deny", callId: "call-deny" });
    establishBoundary(broker, exec);

    await expect(
      broker.execute("write_probe", { note: "deny" }, exec),
    ).rejects.toThrow("approval unavailable");
  });

  test("write tools fail closed when approval service is missing", async () => {
    const broker = await startBroker({ approval: undefined, includeWriteProbe: true });
    const exec = createBrokerExec({ agentId: "agent-missing", callId: "call-missing" });
    establishBoundary(broker, exec);

    await expect(
      broker.execute("write_probe", { note: "missing approval" }, exec),
    ).rejects.toThrow("approval unavailable");

    const status = await broker.execute(
      "paper_status",
      { question: "write count" },
      createBrokerExec({ agentId: "agent-missing", callId: "call-missing-status" }),
    );
    expect(status.structuredContent.write_call_count).toBe(0);
  });

  test("write tools propagate approval cancellation before private MCP call", async () => {
    const approvalCalls = [];
    const broker = await startBroker({
      approval: cancellableApproval(approvalCalls),
      includeWriteProbe: true,
    });
    const controller = new AbortController();
    const exec = createBrokerExec({
      agentId: "agent-cancel",
      callId: "call-cancel",
      signal: controller.signal,
    });
    establishBoundary(broker, exec);
    const pending = broker.execute("write_probe", { note: "cancel" }, exec);

    controller.abort();

    await expect(pending).rejects.toThrow("cancelled");
    expect(approvalCalls).toHaveLength(1);
    const status = await broker.execute(
      "paper_status",
      { question: "write count" },
      createBrokerExec({ agentId: "agent-cancel", callId: "call-cancel-status" }),
    );
    expect(status.structuredContent.write_call_count).toBe(0);
  });

  test("disposed broker generation rejects before approval or private MCP", async () => {
    const approvalCalls = [];
    const broker = await startBroker({
      approval: approval("allowed-once", approvalCalls),
      includeWriteProbe: true,
    });

    await broker.close();

    await expect(
      broker.execute(
        "write_probe",
        { note: "disposed" },
        createBrokerExec({ agentId: "agent-disposed", callId: "call-disposed" }),
      ),
    ).rejects.toThrow("native broker is not active");
    expect(approvalCalls).toHaveLength(0);
  });

  test("mis-scoped broker generation fails closed during activation", async () => {
    await expect(startBroker({ activePresetId: "root" })).rejects.toThrow(
      "native broker scope mismatch",
    );
  });

  test("applies only inherited global allowlist to agent-created restrict", async () => {
    const broker = await startBroker();
    const restrictCalls = [];
    const agent = {
      ctx: {
        tools: {
          restrict(request) {
            restrictCalls.push(request);
          },
        },
      },
    };

    broker.applyAgentCreatedRestriction(agent);

    expect(INHERITED_GLOBAL_ALLOW).toEqual([]);
    expect(restrictCalls).toEqual([{ allow: [] }]);
    expect(restrictCalls[0].allow).not.toContain("skill");
    expect(restrictCalls[0].allow).not.toContain("ask_user_question");
    expect(restrictCalls[0].allow).not.toContain("paper_status");
  });

  test("pre-step catalog invariant rejects extra, missing, or changed tool schemas", async () => {
    const broker = await startBroker();
    const catalog = broker.finalModelCatalog();

    expect(catalog.map((tool) => tool.name)).toEqual([
      ...FINAL_G1_CATALOG_NAMES,
    ]);
    expect(() => broker.assertPreStepToolCatalog(catalog)).not.toThrow();

    expect(() =>
      broker.assertPreStepToolCatalog([
        ...catalog,
        { name: "web_search", description: "blocked", parameters: {} },
      ]),
    ).toThrow("extra=web_search");
    expect(() =>
      broker.assertPreStepToolCatalog(catalog.filter((tool) => tool.name !== "skill")),
    ).toThrow("missing=skill");
    expect(() =>
      broker.assertPreStepToolCatalog(
        catalog.map((tool) =>
          tool.name === "paper_status"
            ? {
                ...tool,
                parameters: {
                  type: "object",
                  properties: {
                    conversation_id: { type: "string" },
                  },
                  additionalProperties: false,
                },
              }
            : tool,
        ),
      ),
    ).toThrow("changed=paper_status");

    expect(toolSchemaHash(catalog.find((tool) => tool.name === "paper_status"))).toMatch(
      /^[a-f0-9]{64}$/,
    );
  });
});
