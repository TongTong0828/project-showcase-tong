import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  PaperRagBrokerGenerationHost,
  PaperRagNativeBroker,
  createBrokerExec,
  redactSecrets,
} from "./broker.mjs";
import { BROKER_MODEL_TOOL_NAMES } from "./paper-rag-tool-catalog.mjs";
import { runDshSessionCompatibilityProof } from "./session-proof.mjs";

const fixtureCommand = process.execPath;
const fixtureArgs = [
  new URL("../fixtures/private-mcp-server.mjs", import.meta.url).pathname,
];
const MODEL_TOOL_NAMES = [...BROKER_MODEL_TOOL_NAMES].sort();

/** @param {string | (() => string)} [value] */
function credentials(value = "probe-test-token") {
  const currentValue = () => (typeof value === "function" ? value() : value);
  return {
    async describe(ref) {
      return { configured: ref === "PAPER_RAG_TEST_TOKEN", writable: false, source: "probe" };
    },
    async resolve(ref) {
      return ref === "PAPER_RAG_TEST_TOKEN"
        ? { value: currentValue(), source: "probe" }
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

function delay(ms) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

async function readAuditLines(path) {
  return (await readFile(path, "utf8"))
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

export async function runBrokerCompatibilityProbe(paths) {
  const cleanup = [];
  function createProbeBroker(options = {}) {
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
    const broker = createProbeBroker(options);
    cleanup.push(() => broker.close());
    await broker.activate();
    return broker;
  }

  try {
    const auditDir = await mkdtemp(join(tmpdir(), "paper-rag-broker-probe-"));
    cleanup.push(() => rm(auditDir, { recursive: true, force: true }));
    const auditPath = join(auditDir, "audit.jsonl");
    const broker = await startBroker({
      childEnv: { PAPER_RAG_PRIVATE_AUDIT_PATH: auditPath },
    });

    const rawToolNames = broker.rawToolNames().sort();
    const modelCatalog = broker.modelCatalog();
    const modelToolNames = modelCatalog.map((tool) => tool.name).sort();
    assert.deepEqual(modelToolNames, MODEL_TOOL_NAMES);
    assert.equal(modelToolNames.some((name) => name.startsWith("mcp__")), false);
    assert.equal(modelToolNames.includes("write_probe"), false);
    assert.equal(rawToolNames.includes("paper_status"), true);
    assert.equal(rawToolNames.includes("write_probe"), true);
    const restrictCalls = [];
    broker.applyAgentCreatedRestriction({
      ctx: {
        tools: {
          restrict(request) {
            restrictCalls.push(request);
          },
        },
      },
    });
    assert.deepEqual(restrictCalls, [{ allow: [] }]);
    const finalModelCatalog = broker.finalModelCatalog();
    broker.assertPreStepToolCatalog(finalModelCatalog);
    assert.throws(
      () =>
        broker.assertPreStepToolCatalog([
          ...finalModelCatalog,
          { name: "web_search", description: "blocked", parameters: {} },
        ]),
      /extra=web_search/,
    );

    const statusArgs = { question: "probe status" };
    const status = await broker.execute(
      "paper_status",
      statusArgs,
      createBrokerExec({ agentId: "agent-probe", callId: "call-probe" }),
    );
    const projection = broker.renderForModel("paper_status", statusArgs, status);
    const projectionText = projection
      .map((block) => (block.type === "text" ? block.text : ""))
      .join("\n");
    assert.equal(status.structuredContent.ok, true);
    assert.equal(status.structuredContent.received_meta.paper_rag, undefined);
    assert.equal(JSON.stringify(status).includes("conversation_id"), false);
    assert.equal(projectionText.includes("ok"), true);
    assert.equal(projectionText.length < 1024, true);

    const [audit] = await readAuditLines(auditPath);
    assert.deepEqual(audit.received_arguments, statusArgs);
    assert.deepEqual(audit.received_meta.paper_rag, {
      conversation_id: "agent-probe",
      actor_id: "system",
      caller: "deepseek_harness",
      tool_call_id: "call-probe",
    });
    assert.equal(JSON.stringify(status.structuredContent.received_arguments).includes("conversation_id"), false);

    const pythonAuditPath = join(auditDir, "python-audit.jsonl");
    const pythonBroker = await startBroker({
      command: join(paths.repoRoot, ".venv/bin/python"),
      args: [new URL("../fixtures/private_mcp_server.py", import.meta.url).pathname],
      childEnv: { PAPER_RAG_PRIVATE_AUDIT_PATH: pythonAuditPath },
    });
    const pythonStatus = await pythonBroker.execute(
      "paper_status",
      { question: "python receiver" },
      createBrokerExec({ agentId: "agent-python", callId: "call-python" }),
    );
    assert.equal(JSON.stringify(pythonStatus).includes("agent-python"), false);
    const [pythonAudit] = await readAuditLines(pythonAuditPath);
    assert.equal(pythonAudit.receiver, "python");
    assert.equal(pythonAudit.received_meta.paper_rag.conversation_id, "agent-python");

    assert.equal(status.structuredContent.has_test_credential, true);
    assert.equal(redactSecrets("token=probe-test-token", ["probe-test-token"]), "token=[REDACTED]");

    const previous = process.env.PAPER_RAG_TEST_TOKEN;
    process.env.PAPER_RAG_TEST_TOKEN = "parent-only-test-token";
    try {
      const noRefBroker = await startBroker({ credentialRefs: [] });
      const noRefStatus = await noRefBroker.execute(
        "paper_status",
        { question: "parent env check" },
        createBrokerExec({ agentId: "agent-parent", callId: "call-parent" }),
      );
      assert.equal(noRefStatus.structuredContent.has_test_credential, false);
    } finally {
      if (previous === undefined) {
        delete process.env.PAPER_RAG_TEST_TOKEN;
      } else {
        process.env.PAPER_RAG_TEST_TOKEN = previous;
      }
    }

    let currentCredential = "initial-test-token";
    const rotatingBroker = await startBroker({
      credentials: credentials(() => currentCredential),
    });
    currentCredential = "rotated-test-token";
    await rotatingBroker.restart();
    const rotated = await rotatingBroker.execute(
      "paper_status",
      { question: "rotated credential" },
      createBrokerExec({ agentId: "agent-rotate", callId: "call-rotate" }),
    );
    assert.equal(rotated.structuredContent.credential_generation, "rotated");
    assert.equal(JSON.stringify(rotated).includes("rotated-test-token"), false);

    const emptyBoundaryApprovalCalls = [];
    const emptyBoundaryBroker = await startBroker({
      approval: approval("allowed-once", emptyBoundaryApprovalCalls),
      includeWriteProbe: true,
    });
    await assert.rejects(
      () =>
        emptyBoundaryBroker.execute(
          "write_probe",
          { note: "empty boundary" },
          createBrokerExec({ agentId: "agent-empty-boundary", callId: "call-empty-boundary" }),
        ),
      /DIRECT_USER_AUTHORITY_REQUIRED/,
    );
    assert.equal(emptyBoundaryApprovalCalls.length, 0);

    const approvalCalls = [];
    const approvedBroker = await startBroker({
      approval: approval("allowed-once", approvalCalls),
      includeWriteProbe: true,
    });
    const approvedExec = createBrokerExec({ agentId: "agent-write", callId: "call-write" });
    const requestBoundaryId = approvedBroker.updateRequestBoundary(approvedExec.agent, [
      { id: "user-approved", source: { kind: "user" } },
    ]);
    assert.equal(
      approvedBroker.updateRequestBoundary(approvedExec.agent, [
        { id: "synthetic-approved", source: { kind: "skill" } },
      ]),
      requestBoundaryId,
    );
    const approved = await approvedBroker.execute(
      "write_probe",
      { note: "allowed" },
      approvedExec,
    );
    assert.equal(approvalCalls.length, 1);
    assert.equal(approved.structuredContent.approved, true);
    assert.equal(JSON.stringify(approved).includes(requestBoundaryId), false);

    const rejectedBroker = await startBroker({
      approval: approval("rejected"),
      includeWriteProbe: true,
    });
    const rejectedExec = createBrokerExec({ agentId: "agent-reject", callId: "call-reject" });
    rejectedBroker.updateRequestBoundary(rejectedExec.agent, [
      { id: "user-rejected", source: { kind: "user" } },
    ]);
    await assert.rejects(
      () =>
        rejectedBroker.execute("write_probe", { note: "rejected" }, rejectedExec),
      /approval rejected/,
    );
    const rejectedStatus = await rejectedBroker.execute(
      "paper_status",
      { question: "write count" },
      createBrokerExec({ agentId: "agent-reject", callId: "call-reject-status" }),
    );
    assert.equal(rejectedStatus.structuredContent.write_call_count, 0);

    const lifecycleAuditPath = join(auditDir, "lifecycle-audit.jsonl");
    const lifecycleBroker = await startBroker({
      childEnv: { PAPER_RAG_PRIVATE_AUDIT_PATH: lifecycleAuditPath },
    });
    const crashedPid = lifecycleBroker.privateMcpPid();
    assert.equal(typeof crashedPid, "number");
    process.kill(crashedPid, "SIGTERM");
    await delay(50);
    await assert.rejects(
      () =>
        lifecycleBroker.execute(
          "paper_status",
          { question: "after crash" },
          createBrokerExec({ agentId: "agent-crash", callId: "call-crash" }),
        ),
      /./,
    );
    await lifecycleBroker.restart();
    const restartedPid = lifecycleBroker.privateMcpPid();
    assert.equal(typeof restartedPid, "number");
    assert.notEqual(restartedPid, crashedPid);
    const recovered = await lifecycleBroker.execute(
      "paper_status",
      { question: "after restart" },
      createBrokerExec({ agentId: "agent-crash", callId: "call-restart" }),
    );
    assert.equal(recovered.structuredContent.ok, true);

    const cancelController = new AbortController();
    const pendingSlowCall = lifecycleBroker.execute(
      "paper_status",
      { question: "slow-cancel" },
      createBrokerExec({
        agentId: "agent-cancel-mcp",
        callId: "call-cancel-mcp",
        signal: cancelController.signal,
      }),
    );
    await delay(25);
    cancelController.abort(new Error("cancelled by probe"));
    await assert.rejects(() => pendingSlowCall, /cancelled by probe/);
    await delay(25);
    const lifecycleAudit = await readAuditLines(lifecycleAuditPath);
    assert.equal(lifecycleAudit.some((line) => line.lifecycle === "cancelled"), true);
    const afterCancel = await lifecycleBroker.execute(
      "paper_status",
      { question: "after cancel" },
      createBrokerExec({ agentId: "agent-cancel-mcp", callId: "call-after-cancel" }),
    );
    assert.equal(afterCancel.structuredContent.ok, true);

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
    const boundaryA = lifecycleBroker.updateRequestBoundary(agentA.agent, [
      { id: "user-a", source: { kind: "user" } },
    ]);
    const boundaryB = lifecycleBroker.updateRequestBoundary(agentB.agent, [
      { id: "user-b", source: { kind: "user" } },
    ]);
    assert.notEqual(boundaryA, boundaryB);
    assert.equal(lifecycleBroker.privateMcpPid(), restartedPid);

    const generationHost = new PaperRagBrokerGenerationHost({
      brokerFactory: () => createProbeBroker(),
    });
    cleanup.push(() => generationHost.shutdown());
    const generationA = await generationHost.acquire("generation-1", "agent-a");
    const generationB = await generationHost.acquire("generation-1", "agent-b");
    const generationOnePid = generationA.broker.privateMcpPid();
    assert.equal(typeof generationOnePid, "number");
    assert.equal(generationB.broker, generationA.broker);
    await generationA.release();
    assert.equal(
      generationHost.diagnostics().live_private_mcp_pids.includes(generationOnePid),
      true,
    );
    const afterRelease = await generationB.broker.execute(
      "paper_status",
      { question: "after generation release" },
      createBrokerExec({ agentId: "agent-b", callId: "call-generation-b" }),
    );
    assert.equal(afterRelease.structuredContent.ok, true);

    const generationC = await generationHost.acquire("generation-2", "agent-c");
    const generationTwoPid = generationC.broker.privateMcpPid();
    assert.equal(typeof generationTwoPid, "number");
    assert.notEqual(generationTwoPid, generationOnePid);
    const generationDiagnostics = generationHost.diagnostics();
    assert.equal(generationDiagnostics.generation_count, 2);
    assert.equal(generationDiagnostics.retained_generation_count, 2);
    assert.equal(generationDiagnostics.generations.length, 2);
    await generationB.release();
    await generationC.release();
    assert.equal(generationHost.diagnostics().generation_count, 2);
    await generationHost.shutdown();
    assert.equal(generationHost.diagnostics().generation_count, 0);
    assert.deepEqual(generationHost.diagnostics().live_private_mcp_pids, []);

    await assert.rejects(() => startBroker({ activePresetId: "root" }), /scope mismatch/);

    const dshSession = runDshSessionCompatibilityProof(paths);

    return {
      passed: true,
      mcp_boundary: {
        raw_tool_names: rawToolNames,
        model_tool_names: modelToolNames,
        canonical_result_keys: Object.keys(status.structuredContent).sort(),
        bounded_projection_bytes: projectionText.length,
        hidden_metadata_wire: "tools/call.params._meta.paper_rag",
        python_receiver_verified: true,
        result_private_metadata_stripped: true,
      },
      credential_bridge: {
        explicit_child_env: true,
        parent_env_not_inherited_without_ref: true,
        rotation: "new child generation",
        redaction: true,
      },
      catalog_policy: {
        inherited_global_allow: [],
        final_model_tool_names: finalModelCatalog.map((tool) => tool.name),
        restrict_receives_only_inherited_global_allow: true,
        extra_tool_rejected_before_model_request: true,
      },
      request_boundary: {
        empty_boundary_denies_write_before_approval: true,
        synthetic_messages_inherit_boundary: true,
        boundary_hidden_from_result: true,
      },
      approval_bridge: {
        allowed_once_calls_private_mcp: true,
        rejected_skips_private_mcp: true,
        mis_scoped_generation_fails_closed: true,
        request_shape: "agent,toolName,callId,reason,signal",
      },
      lifecycle: {
        child_crash_is_diagnosable: true,
        restart_restores_private_mcp: true,
        cancellation_aborts_inflight_call: true,
        child_usable_after_cancellation: true,
        multi_agent_boundaries_are_isolated: true,
        standing_generation_child_shared_by_agents: true,
        dispose_agent_keeps_shared_child_alive: true,
        preset_edit_creates_new_generation: true,
        generation_count_is_diagnostic: true,
        host_shutdown_closes_all_generations: true,
      },
      dsh_session: dshSession,
    };
  } finally {
    while (cleanup.length > 0) {
      await cleanup.pop()();
    }
  }
}
