import { join } from "node:path";

import {
  PaperRagNativeBroker,
  buildPaperRagMcpChildEnv,
  environmentCredentialProvider,
  registerPaperRagNativeTools,
} from "./broker.mjs";

const DEFAULT_CREDENTIAL_REFS = Object.freeze(["OPENAI_API_KEY", "DEEPSEEK_API_KEY"]);
export const DEFAULT_MCP_ARGS = Object.freeze(["-m", "paper_rag.mcp"]);
const ISOLATED_APPROVAL_MODE = "isolated";
const LIVE_SMOKE_WRITE_TOOLS = new Set([
  "paper_ingest",
  "discovery_candidate_ingest",
  "paper_deliver",
]);

export const name = "paper-rag-native-broker";
export const inject = ["tools", "credentials"];

export function credentialProviderForContext(ctx) {
  return ctx?.credentials ?? ctx?.get?.("credentials") ?? environmentCredentialProvider();
}

export function registerPaperRagRequestBoundaryTracking(ctx, broker) {
  if (typeof ctx?.on !== "function") {
    return () => {};
  }
  return (
    ctx.on("agent/inbox/claimed", ({ agent, message }) => {
      broker.updateRequestBoundary(agent, [message]);
    }) ?? (() => {})
  );
}

function isLiveG2WorkspacePath(value) {
  return (
    typeof value === "string" &&
    /(?:^|[/\\])data[/\\]index[/\\]migration-gates[/\\]live-workspaces[/\\]G2[/\\]/.test(
      value,
    )
  );
}

export function shouldAllowIsolatedBrokerApproval(req, env = process.env) {
  if (env.PAPER_RAG_DSH_HEADLESS_APPROVE_WRITES !== ISOLATED_APPROVAL_MODE) {
    return false;
  }
  if (!LIVE_SMOKE_WRITE_TOOLS.has(req?.toolName)) {
    return false;
  }
  if (typeof req?.reason !== "string" || !req.reason.includes(req.toolName)) {
    return false;
  }
  return (
    isLiveG2WorkspacePath(env.PAPER_RAG_CONFIG) &&
    isLiveG2WorkspacePath(env.PAPER_RAG_ARTIFACT_ROOT)
  );
}

export function paperRagApprovalService(baseApproval, env = process.env) {
  return {
    async request(req) {
      if (shouldAllowIsolatedBrokerApproval(req, env)) {
        return "allowed-once";
      }
      if (typeof baseApproval?.request !== "function") {
        throw new Error(`approval unavailable for ${req?.toolName ?? "Paper RAG write"}`);
      }
      return baseApproval.request(req);
    },
  };
}

function parseJsonArrayEnv(name, fallback) {
  const value = process.env[name];
  if (value === undefined || value.trim() === "") {
    return [...fallback];
  }
  const parsed = JSON.parse(value);
  if (!Array.isArray(parsed) || parsed.some((item) => typeof item !== "string")) {
    throw new Error(`${name} must be a JSON array of strings`);
  }
  return parsed;
}

export async function apply(ctx) {
  const repoRoot = process.env.PAPER_RAG_REPO_ROOT ?? process.cwd();
  const broker = new PaperRagNativeBroker({
    command: process.env.PAPER_RAG_MCP_COMMAND ?? join(repoRoot, ".venv/bin/python"),
    args: parseJsonArrayEnv("PAPER_RAG_MCP_ARGS", DEFAULT_MCP_ARGS),
    cwd: repoRoot,
    credentials: credentialProviderForContext(ctx),
    credentialRefs: parseJsonArrayEnv("PAPER_RAG_MCP_CREDENTIAL_REFS", DEFAULT_CREDENTIAL_REFS),
    childEnv: buildPaperRagMcpChildEnv({
      repoRoot,
      artifactRoot: process.env.PAPER_RAG_ARTIFACT_ROOT ?? join(repoRoot, "data/artifacts"),
      importRoot: process.env.PAPER_RAG_IMPORT_ROOT ?? join(repoRoot, "data/imports"),
      sourceEnv: process.env,
      toolset: process.env.PAPER_RAG_MCP_TOOLSET ?? "research",
      actorId: process.env.PAPER_RAG_ACTOR_ID ?? "system",
    }),
    activePresetId: process.env.PAPER_RAG_DSH_PRESET_ID ?? "paper-research",
    approval: paperRagApprovalService(ctx.get?.("approval")),
  });

  try {
    await broker.activate();
    const unregisterTools = registerPaperRagNativeTools(ctx, broker);
    const unregisterBoundaryTracking = registerPaperRagRequestBoundaryTracking(ctx, broker);
    ctx.effect(
      () => async () => {
        unregisterBoundaryTracking();
        unregisterTools();
        await broker.close();
      },
      "paper-rag-native-broker",
    );
  } catch (error) {
    await broker.close().catch(() => {});
    throw error;
  }
}
