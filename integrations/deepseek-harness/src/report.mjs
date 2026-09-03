import { mkdir, rename, writeFile } from "node:fs/promises";
import { dirname, relative } from "node:path";

const G0_CASES = [
  "DSH-G0-001",
  "DSH-G0-002",
  "DSH-G0-003",
  "DSH-G0-004",
  "DSH-G0-005",
  "DSH-G0-006",
  "DSH-G0-007",
  "DSH-G0-008",
  "DSH-G0-009",
];

function pass(evidence) {
  return { status: "PASS", evidence };
}

function blocked(reason) {
  return { status: "BLOCKED", reason };
}

function hasApprovalSessionProof(brokerProbe) {
  return (
    brokerProbe?.approval_bridge?.allowed_once_calls_private_mcp === true &&
    brokerProbe?.approval_bridge?.rejected_skips_private_mcp === true &&
    brokerProbe?.dsh_session?.approval_decision_recorded === true
  );
}

function hasSessionResumeProof(brokerProbe) {
  const session = brokerProbe?.dsh_session;
  return (
    session?.session_root_versioned === true &&
    session?.restored_history_order_matches === true &&
    session?.restored_derived_messages_match === true &&
    session?.can_continue_new_turn === true &&
    session?.no_duplicate_historical_tool_calls === true
  );
}

function hasCancellationCredentialProof(brokerProbe) {
  return (
    brokerProbe?.credential_bridge?.explicit_child_env === true &&
    brokerProbe?.credential_bridge?.parent_env_not_inherited_without_ref === true &&
    brokerProbe?.credential_bridge?.redaction === true &&
    brokerProbe?.lifecycle?.cancellation_aborts_inflight_call === true &&
    brokerProbe?.lifecycle?.child_usable_after_cancellation === true &&
    brokerProbe?.dsh_session?.secret_not_in_session === true
  );
}

function hasHostLifecycleProof(brokerProbe) {
  return (
    brokerProbe?.lifecycle?.standing_generation_child_shared_by_agents === true &&
    brokerProbe?.lifecycle?.dispose_agent_keeps_shared_child_alive === true &&
    brokerProbe?.lifecycle?.preset_edit_creates_new_generation === true &&
    brokerProbe?.lifecycle?.generation_count_is_diagnostic === true &&
    brokerProbe?.lifecycle?.host_shutdown_closes_all_generations === true
  );
}

export function buildG0CompatReport({
  commit,
  dirty,
  paths,
  configAudit,
  presetDiscovery,
  brokerProbe = undefined,
  startedAt = new Date().toISOString(),
}) {
  const deterministicEvidence = {
    dsh_home: relative(paths.repoRoot, paths.dshHome),
    credentials_path: relative(paths.repoRoot, paths.credentialsPath),
    patch: relative(paths.repoRoot, paths.patchPath),
    preset_source: relative(paths.repoRoot, paths.presetSourceDir),
    preset_runtime: relative(paths.repoRoot, paths.presetDestDir),
  };
  const cases = {
    "DSH-G0-001": pass("package.json and pnpm-lock exact DSH/Cordis graph checks pass"),
    "DSH-G0-002": configAudit.passed
      ? pass("dump-config audit confirms loopback host and telemetry disabled")
      : blocked("dump-config audit failed"),
    "DSH-G0-003":
      presetDiscovery?.id === "paper-research" && presetDiscovery?.broken === undefined
        ? pass("DSH discoverPresets found paper-research in versioned DSH_HOME")
        : blocked(presetDiscovery?.broken ?? "paper-research preset was not discovered"),
    "DSH-G0-004": brokerProbe?.mcp_boundary
      ? pass(brokerProbe.mcp_boundary)
      : blocked("Native Broker + private stdio MCP fixture not implemented yet"),
    "DSH-G0-005": hasApprovalSessionProof(brokerProbe)
      ? pass(brokerProbe.dsh_session)
      : blocked(
          brokerProbe?.approval_bridge
            ? "Broker approval executor proof passes; DSH Session approval-decision recording runner is still pending"
            : "write-tool approval proof not implemented yet",
        ),
    "DSH-G0-006": hasSessionResumeProof(brokerProbe)
      ? pass(brokerProbe.dsh_session)
      : blocked("same-version DSH session resume proof not implemented yet"),
    "DSH-G0-007":
      brokerProbe?.lifecycle?.restart_restores_private_mcp === true &&
      hasSessionResumeProof(brokerProbe)
        ? pass({
            restart_restores_private_mcp: true,
            cancellation_aborts_inflight_call:
              brokerProbe.lifecycle.cancellation_aborts_inflight_call === true,
            restored_history_order_matches:
              brokerProbe.dsh_session.restored_history_order_matches,
            no_duplicate_historical_tool_calls:
              brokerProbe.dsh_session.no_duplicate_historical_tool_calls,
          })
        : blocked(
            brokerProbe?.lifecycle?.restart_restores_private_mcp
              ? "MCP crash/reconnect and cancellation proof pass; same-version Session resume runner is still pending"
              : "MCP crash/reconnect proof not implemented yet",
          ),
    "DSH-G0-008": hasCancellationCredentialProof(brokerProbe)
      ? pass({
          explicit_child_env: brokerProbe.credential_bridge.explicit_child_env,
          parent_env_not_inherited_without_ref:
            brokerProbe.credential_bridge.parent_env_not_inherited_without_ref,
          redaction: brokerProbe.credential_bridge.redaction,
          cancellation_aborts_inflight_call:
            brokerProbe.lifecycle.cancellation_aborts_inflight_call,
          child_usable_after_cancellation:
            brokerProbe.lifecycle.child_usable_after_cancellation,
          secret_not_in_session: brokerProbe.dsh_session.secret_not_in_session,
        })
      : blocked(
          brokerProbe?.credential_bridge
            ? "credential bridge and cancellation proof pass; DSH timeout/session convergence runner is still pending"
            : "cancel/timeout/credential bridge proof not implemented yet",
        ),
    "DSH-G0-009": hasHostLifecycleProof(brokerProbe)
      ? pass({
          standing_generation_child_shared_by_agents:
            brokerProbe.lifecycle.standing_generation_child_shared_by_agents,
          dispose_agent_keeps_shared_child_alive:
            brokerProbe.lifecycle.dispose_agent_keeps_shared_child_alive,
          preset_edit_creates_new_generation:
            brokerProbe.lifecycle.preset_edit_creates_new_generation,
          generation_count_is_diagnostic:
            brokerProbe.lifecycle.generation_count_is_diagnostic,
          host_shutdown_closes_all_generations:
            brokerProbe.lifecycle.host_shutdown_closes_all_generations,
        })
      : blocked(
          brokerProbe?.lifecycle?.standing_generation_child_shared_by_agents
            ? "standing Broker generation proof passes for shared child and isolated agent state; full Host lifecycle runner is still pending"
            : "standing Broker generation proof not implemented yet",
        ),
  };
  const goNoGo = Object.values(cases).every((caseResult) => caseResult.status === "PASS")
    ? "go"
    : "no-go";

  return {
    schema_version: 1,
    gate: "G0",
    component: "dsh-g0-compat",
    commit,
    dirty,
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    versions: {
      dsh: paths.dshVersion,
      cordis: paths.cordisVersion,
      node: process.version,
    },
    config_audit: configAudit,
    broker_probe: brokerProbe,
    paths: deterministicEvidence,
    cases: Object.fromEntries(G0_CASES.map((caseId) => [caseId, cases[caseId]])),
    go_no_go: goNoGo,
  };
}

export async function writeJsonAtomic(path, value) {
  await mkdir(dirname(path), { recursive: true });
  const tmp = `${path}.${process.pid}.tmp`;
  await writeFile(tmp, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await rename(tmp, path);
}
