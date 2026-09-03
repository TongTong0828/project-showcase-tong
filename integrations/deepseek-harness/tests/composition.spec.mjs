import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, test } from "vitest";

import { auditDshConfigDump } from "../src/config-audit.mjs";
import { dshEnvironment, pathsFor } from "../src/paths.mjs";
import { discoverPaperResearchPreset } from "../src/preset-discovery.mjs";
import { buildG0CompatReport } from "../src/report.mjs";
import { withRuntimeLock } from "../src/runtime-lock.mjs";
import { syncPaperResearchPreset } from "../src/sync-preset.mjs";

const integrationRoot = fileURLToPath(new URL("..", import.meta.url));
const repoRoot = resolve(integrationRoot, "../..");
const cleanup = [];

afterEach(async () => {
  while (cleanup.length > 0) {
    const path = cleanup.pop();
    await rm(path, { recursive: true, force: true });
  }
});

describe("repo-local DeepSeek Harness runtime", () => {
  test("uses versioned DSH_HOME and a credential store outside the session root", () => {
    const paths = pathsFor({ integrationRoot });

    expect(paths.repoRoot).toBe(repoRoot);
    expect(paths.dshVersion).toBe("0.1.0-rc.6");
    expect(paths.dshHome).toBe(
      join(repoRoot, "data/runtime/deepseek-harness/versions/0.1.0-rc.6"),
    );
    expect(paths.sessionRoot).toBe(join(paths.dshHome, "sessions"));
    expect(paths.credentialsPath).toBe(
      join(repoRoot, "data/runtime/deepseek-harness/credentials/.credentials.yaml"),
    );
    expect(paths.credentialsPath.startsWith(paths.dshHome)).toBe(false);
  });

  test("defaults the local web runtime to the local Paper RAG config", () => {
    const paths = pathsFor({ integrationRoot });

    expect(dshEnvironment(paths).PAPER_RAG_CONFIG).toBe(
      join(repoRoot, "config/local.yaml"),
    );
    expect(dshEnvironment(paths).CHAT_MODEL).toBe("deepseek-v4-flash");
  });

  test("syncs the paper-research preset into DSH_HOME user presets", async () => {
    const dshHome = await mkdtemp(join(tmpdir(), "paper-rag-dsh-home-"));
    cleanup.push(dshHome);
    const paths = pathsFor({ integrationRoot, dshHome });

    const result = await syncPaperResearchPreset(paths);

    expect(result.id).toBe("paper-research");
    expect(result.destDir).toBe(join(dshHome, ".agent-presets/paper-research"));
    expect((await stat(result.destDir)).isDirectory()).toBe(true);
    await expect(readFile(join(result.destDir, "preset.yml"), "utf8")).resolves.toContain(
      "Paper Research",
    );
    const syncedAgent = await readFile(join(result.destDir, "agent.cordis.yml"), "utf8");
    expect(syncedAgent).toContain("@deepseek-ai/dsh-tool-ask-user");
    expect(syncedAgent).toContain("paper-rag-native-broker-plugin.mjs");
    expect(syncedAgent).toContain("paper_discover");
    expect(syncedAgent).toContain("discovery_candidate_ingest");
    expect(syncedAgent).toContain("paper_deliver");
    expect(syncedAgent).toContain("Candidate results are not Paper RAG answer evidence");
    expect(syncedAgent).toContain("deepseek-v4-flash");
    const syncedBrokerWrapper = await readFile(
      join(result.destDir, "paper-rag-native-broker-plugin.mjs"),
      "utf8",
    );
    expect(syncedBrokerWrapper).toContain('export const inject = ["tools", "credentials"]');

    const discovered = await discoverPaperResearchPreset(paths);
    expect(discovered).toMatchObject({
      id: "paper-research",
      trust: "user",
      name: "Paper Research",
    });
    expect(discovered.broken).toBeUndefined();
    expect(discovered.path).toBe(join(result.destDir, "agent.cordis.yml"));
  });

  test("sync is safe when doctor and smoke bootstrap the same DSH_HOME concurrently", async () => {
    const dshHome = await mkdtemp(join(tmpdir(), "paper-rag-dsh-home-"));
    cleanup.push(dshHome);
    const paths = pathsFor({ integrationRoot, dshHome });

    await Promise.all([
      syncPaperResearchPreset(paths),
      syncPaperResearchPreset(paths),
      syncPaperResearchPreset(paths),
      syncPaperResearchPreset(paths),
    ]);

    const discovered = await discoverPaperResearchPreset(paths);
    expect(discovered.broken).toBeUndefined();
    await expect(
      readFile(join(dshHome, ".agent-presets/paper-research/preset.yml"), "utf8"),
    ).resolves.toContain("Paper Research");
  });

  test("runtime lock serializes DSH profile writers", async () => {
    const dshHome = await mkdtemp(join(tmpdir(), "paper-rag-dsh-home-"));
    cleanup.push(dshHome);
    const paths = pathsFor({ integrationRoot, dshHome });
    let active = 0;
    let maxActive = 0;

    await Promise.all(
      Array.from({ length: 4 }, () =>
        withRuntimeLock(paths, async () => {
          active += 1;
          maxActive = Math.max(maxActive, active);
          await new Promise((resolvePromise) => setTimeout(resolvePromise, 5));
          active -= 1;
        }),
      ),
    );

    expect(maxActive).toBe(1);
  });
});

describe("web profile config audit", () => {
  test("requires loopback, disabled telemetry, paper preset default, and timeout policy", () => {
    const dump = `
- id: session-telemetry-otel
  name: '@deepseek-ai/dsh-session-telemetry-otel'
  disabled: true
- id: credentials
  name: '@deepseek-ai/dsh-credentials-local'
  config:
    path: !!js process.env.PAPER_RAG_DSH_CREDENTIALS_PATH
- id: webserver
  name: '@deepseek-ai/dsh-host-webserver'
  config:
    host: 127.0.0.1
- id: timeout-policy
  name: '@deepseek-ai/dsh-tool-call-timeout-policy'
- id: agent-presets
  name: '@deepseek-ai/dsh-agent-presets'
  config:
    default: paper-research
`;

    const audit = auditDshConfigDump(dump);

    expect(audit.passed).toBe(true);
    expect(audit.checks.map((check) => check.id)).toEqual([
      "web-loopback",
      "telemetry-disabled",
      "credential-path",
      "timeout-policy",
      "paper-preset-default",
    ]);
  });

  test("fails closed when timeout policy is missing", () => {
    const audit = auditDshConfigDump(`
- id: webserver
  config:
    host: 127.0.0.1
- id: session-telemetry-otel
  disabled: true
- id: credentials
  config:
    path: !!js process.env.PAPER_RAG_DSH_CREDENTIALS_PATH
- id: agent-presets
  config:
    default: paper-research
`);

    expect(audit.passed).toBe(false);
    expect(audit.checks.find((check) => check.id === "timeout-policy")).toMatchObject({
      status: "FAIL",
    });
  });
});

describe("G0 component report", () => {
  test("marks deterministic DSH checks pass and unfinished live compatibility cases blocked", () => {
    const paths = pathsFor({ integrationRoot });
    const report = buildG0CompatReport({
      commit: "abc123",
      dirty: false,
      paths,
      configAudit: { passed: true, checks: [] },
      presetDiscovery: { id: "paper-research", broken: undefined },
    });

    expect(report.gate).toBe("G0");
    expect(report.component).toBe("dsh-g0-compat");
    expect(report.go_no_go).toBe("no-go");
    expect(report.versions).toMatchObject({
      dsh: "0.1.0-rc.6",
      cordis: "4.0.1",
    });
    expect(report.cases["DSH-G0-001"].status).toBe("PASS");
    expect(report.cases["DSH-G0-002"].status).toBe("PASS");
    expect(report.cases["DSH-G0-003"].status).toBe("PASS");
    expect(report.cases["DSH-G0-003"].evidence).toContain("discoverPresets");
    expect(report.cases["DSH-G0-004"].status).toBe("BLOCKED");
    expect(report.cases["DSH-G0-009"].status).toBe("BLOCKED");
  });

  test("marks the private MCP boundary pass when broker probe evidence exists", () => {
    const paths = pathsFor({ integrationRoot });
    const report = buildG0CompatReport({
      commit: "abc123",
      dirty: false,
      paths,
      configAudit: { passed: true, checks: [] },
      presetDiscovery: { id: "paper-research", broken: undefined },
      brokerProbe: {
        mcp_boundary: {
          raw_tool_names: ["paper_status", "write_probe"],
          model_tool_names: ["paper_status", "paper_list", "paper_search", "paper_qa", "paper_section", "paper_compare", "wiki_lookup"],
          bounded_projection_bytes: 11,
          hidden_metadata_wire: "tools/call.params._meta.paper_rag",
          result_private_metadata_stripped: true,
        },
        approval_bridge: {
          allowed_once_calls_private_mcp: true,
          rejected_skips_private_mcp: true,
        },
        credential_bridge: {
          explicit_child_env: true,
          parent_env_not_inherited_without_ref: true,
          rotation: "new child generation",
          redaction: true,
        },
      },
    });

    expect(report.cases["DSH-G0-004"].status).toBe("PASS");
    expect(report.cases["DSH-G0-004"].evidence).toMatchObject({
      hidden_metadata_wire: "tools/call.params._meta.paper_rag",
      result_private_metadata_stripped: true,
    });
    expect(report.cases["DSH-G0-005"]).toMatchObject({
      status: "BLOCKED",
      reason: expect.stringContaining("Session"),
    });
    expect(report.cases["DSH-G0-008"]).toMatchObject({
      status: "BLOCKED",
      reason: expect.stringContaining("timeout"),
    });
  });

  test("marks Session-dependent G0 cases pass when DSH Session proof exists", () => {
    const paths = pathsFor({ integrationRoot });
    const dshSession = {
      session_format_version: 0,
      session_root_versioned: true,
      restored_history_order_matches: true,
      restored_derived_messages_match: true,
      tool_call_arguments_are_model_only: true,
      hidden_metadata_not_in_session: true,
      secret_not_in_session: true,
      approval_decision_recorded: true,
      can_continue_new_turn: true,
      no_duplicate_historical_tool_calls: true,
    };
    const report = buildG0CompatReport({
      commit: "abc123",
      dirty: false,
      paths,
      configAudit: { passed: true, checks: [] },
      presetDiscovery: { id: "paper-research", broken: undefined },
      brokerProbe: {
        mcp_boundary: {
          raw_tool_names: ["paper_status", "write_probe"],
          model_tool_names: ["paper_status", "paper_list", "paper_search", "paper_qa", "paper_section", "paper_compare", "wiki_lookup"],
          hidden_metadata_wire: "tools/call.params._meta.paper_rag",
          python_receiver_verified: true,
          result_private_metadata_stripped: true,
        },
        approval_bridge: {
          allowed_once_calls_private_mcp: true,
          rejected_skips_private_mcp: true,
        },
        credential_bridge: {
          explicit_child_env: true,
          parent_env_not_inherited_without_ref: true,
          redaction: true,
        },
        lifecycle: {
          restart_restores_private_mcp: true,
          cancellation_aborts_inflight_call: true,
          child_usable_after_cancellation: true,
          standing_generation_child_shared_by_agents: true,
          dispose_agent_keeps_shared_child_alive: true,
          preset_edit_creates_new_generation: true,
          generation_count_is_diagnostic: true,
          host_shutdown_closes_all_generations: true,
        },
        dsh_session: dshSession,
      },
    });

    expect(report.cases["DSH-G0-005"]).toEqual({ status: "PASS", evidence: dshSession });
    expect(report.cases["DSH-G0-006"]).toEqual({ status: "PASS", evidence: dshSession });
    expect(report.cases["DSH-G0-007"]).toMatchObject({
      status: "PASS",
      evidence: {
        restart_restores_private_mcp: true,
        restored_history_order_matches: true,
        no_duplicate_historical_tool_calls: true,
      },
    });
    expect(report.cases["DSH-G0-008"]).toMatchObject({
      status: "PASS",
      evidence: {
        explicit_child_env: true,
        cancellation_aborts_inflight_call: true,
        secret_not_in_session: true,
      },
    });
    expect(report.cases["DSH-G0-009"]).toMatchObject({
      status: "PASS",
      evidence: {
        standing_generation_child_shared_by_agents: true,
        dispose_agent_keeps_shared_child_alive: true,
        preset_edit_creates_new_generation: true,
        generation_count_is_diagnostic: true,
        host_shutdown_closes_all_generations: true,
      },
    });
    expect(report.go_no_go).toBe("go");
  });
});
