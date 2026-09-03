import { createHash } from "node:crypto";
import { delimiter, join } from "node:path";

import { credentialRef } from "@deepseek-ai/dsh-credentials";
import { defineTool } from "@deepseek-ai/dsh-tools";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { CallToolResultSchema } from "@modelcontextprotocol/sdk/types.js";

import {
  BROKER_MODEL_TOOL_NAMES,
  approvalReasonForTool,
  approvalRequired,
  brokerToolConfig,
} from "./paper-rag-tool-catalog.mjs";
import {
  presentPaperRagResult,
  renderPaperRagResultForModel,
} from "./paper-rag-cards.mjs";

const BROKER_CALLER = "deepseek_harness";
const APPROVAL_ALLOW_ONCE = "allowed-once";
const REQUEST_BOUNDARY_NAMESPACE = "3ef5d38b-0fcb-5ec8-9f49-6fc0b9b7c4ec";
const DEFAULT_MCP_REQUEST_TIMEOUT_MS = 120_000;
const MCP_REQUEST_TIMEOUT_MS_BY_TOOL = Object.freeze({
  discovery_candidate_ingest: 420_000,
  discovery_run_get: 120_000,
  paper_compare: 240_000,
  paper_deliver: 300_000,
  paper_discover: 180_000,
  paper_ingest: 420_000,
  paper_qa: 240_000,
  paper_section: 180_000,
});
const MCP_CHILD_ENV_ALLOWLIST = Object.freeze([
  "CHAT_MODEL",
  "DEEPSEEK_BASE_URL",
  "FEEDBACK_SQLITE_PATH",
  "HOME",
  "OPENAI_BASE_URL",
  "PAPER_RAG_CONFIG",
  "PATH",
  "REQUESTS_CA_BUNDLE",
  "SMALL_MODEL",
  "SSL_CERT_FILE",
  "TMPDIR",
]);

export const INHERITED_GLOBAL_ALLOW = Object.freeze([]);
export const PRESET_LOCAL_MODEL_TOOLS = Object.freeze([
  Object.freeze({
    name: "skill",
    description: "Read project-local Paper Research skill guidance.",
    parameters: Object.freeze({
      type: "object",
      properties: Object.freeze({}),
      additionalProperties: false,
    }),
  }),
  Object.freeze({
    name: "ask_user_question",
    description: "Ask the human for missing research intent.",
    parameters: Object.freeze({
      type: "object",
      properties: Object.freeze({
        question: Object.freeze({ type: "string" }),
      }),
      required: Object.freeze(["question"]),
      additionalProperties: false,
    }),
  }),
]);

function jsonContent(value) {
  return [{ type: "text", text: JSON.stringify(value) }];
}

/** @param {any} value */
function renderMcpResult(_args, value) {
  return Array.isArray(value?.content) ? value.content : jsonContent(value);
}

export function mcpRequestTimeoutForTool(name) {
  return MCP_REQUEST_TIMEOUT_MS_BY_TOOL[name] ?? DEFAULT_MCP_REQUEST_TIMEOUT_MS;
}

export function mcpRequestOptionsForTool(name, signal) {
  return {
    signal,
    timeout: mcpRequestTimeoutForTool(name),
    resetTimeoutOnProgress: true,
  };
}

function replaceAllLiteral(text, needle, replacement) {
  return text.split(needle).join(replacement);
}

export function redactSecrets(value, secrets = []) {
  let text = String(value);
  for (const secret of secrets) {
    if (typeof secret !== "string" || secret.length === 0) {
      continue;
    }
    text = replaceAllLiteral(text, secret, "[REDACTED]");
  }
  return text;
}

export function environmentCredentialProvider(sourceEnv = process.env) {
  return {
    async describe(ref) {
      return {
        configured: typeof sourceEnv[ref] === "string" && sourceEnv[ref].length > 0,
        writable: false,
        source: "environment",
      };
    },
    async resolve(ref) {
      const value = sourceEnv[ref];
      return typeof value === "string" && value.length > 0
        ? { value, source: "environment" }
        : undefined;
    },
  };
}

/**
 * @param {{
 *   repoRoot?: string,
 *   artifactRoot?: string,
 *   importRoot?: string,
 *   toolset?: string,
 *   actorId?: string,
 *   sourceEnv?: Record<string, string | undefined>,
 * }} options
 * @returns {Record<string, string>}
 */
export function buildPaperRagMcpChildEnv({
  repoRoot,
  artifactRoot,
  importRoot,
  toolset = "readonly",
  actorId = "system",
  sourceEnv = process.env,
} = {}) {
  if (typeof repoRoot !== "string" || repoRoot.length === 0) {
    throw new Error("repoRoot is required for Paper RAG MCP child env");
  }

  /** @type {Record<string, string>} */
  const env = {
    PAPER_RAG_ACTOR_ID: actorId,
    PAPER_RAG_MCP_TOOLSET: toolset,
  };
  const srcPath = join(repoRoot, "src");
  env.PYTHONPATH =
    typeof sourceEnv.PYTHONPATH === "string" && sourceEnv.PYTHONPATH.length > 0
      ? `${srcPath}${delimiter}${sourceEnv.PYTHONPATH}`
      : srcPath;
  if (typeof artifactRoot === "string" && artifactRoot.length > 0) {
    env.PAPER_RAG_ARTIFACT_ROOT = artifactRoot;
  }
  if (typeof importRoot === "string" && importRoot.length > 0) {
    env.PAPER_RAG_IMPORT_ROOT = importRoot;
  }

  for (const key of MCP_CHILD_ENV_ALLOWLIST) {
    const value = sourceEnv[key];
    if (typeof value === "string" && value.length > 0) {
      env[key] = value;
    }
  }
  return env;
}

export function registerPaperRagNativeTools(ctx, broker) {
  if (typeof ctx?.tools?.register !== "function") {
    throw new Error("DSH tools registry unavailable for Paper RAG native broker");
  }
  const disposers = broker.toolDefinitions().map((tool) => ctx.tools.register(tool));
  let disposed = false;
  return () => {
    if (disposed) {
      return;
    }
    disposed = true;
    for (const dispose of disposers.slice().reverse()) {
      dispose();
    }
  };
}

/**
 * @param {{ agentId?: string, sessionId?: string, callId?: string, signal?: AbortSignal }} [options]
 */
export function createBrokerExec(options = {}) {
  const { agentId, sessionId, callId, signal } = options;
  const controller = signal === undefined ? new AbortController() : undefined;
  const effectiveSignal = signal ?? controller.signal;
  const effectiveAgentId = agentId ?? "paper-rag-agent";
  const effectiveCallId = callId ?? "paper-rag-call";

  return {
    callId: effectiveCallId,
    rootCallId: effectiveCallId,
    token: Symbol("paper-rag-broker-exec-token"),
    name: "",
    arguments: {},
    signal: effectiveSignal,
    agent: {
      id: effectiveAgentId,
      session: {
        id: sessionId ?? effectiveAgentId,
        events: [],
      },
    },
    deferContext() {},
    concludeTurn() {},
  };
}

function paperRagMeta(exec, extra = {}) {
  return {
    conversation_id: exec?.agent?.id ?? exec?.agent?.session?.id ?? "unknown",
    actor_id: "system",
    caller: BROKER_CALLER,
    tool_call_id: exec?.callId ?? exec?.rootCallId ?? "unknown",
    ...extra,
  };
}

function redactResult(result, secrets) {
  const serialized = JSON.stringify(result);
  const redacted = redactSecrets(serialized, secrets);
  return stripPrivateMetadata(JSON.parse(redacted));
}

function stripPrivateMetadata(value) {
  if (Array.isArray(value)) {
    return value.map((item) => stripPrivateMetadata(item));
  }
  if (value === null || typeof value !== "object") {
    return value;
  }

  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => key !== "paper_rag")
      .map(([key, item]) => [key, stripPrivateMetadata(item)]),
  );
}

function canonicalJson(value) {
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function toolSchemaHash(tool) {
  return createHash("sha256")
    .update(canonicalJson(tool.parameters ?? {}))
    .digest("hex");
}

function catalogSignature(tools) {
  return new Map(
    tools
      .map((tool) => [tool.name, toolSchemaHash(tool)])
      .sort(([left], [right]) => left.localeCompare(right)),
  );
}

function uuidBytes(uuid) {
  return Buffer.from(uuid.replaceAll("-", ""), "hex");
}

function formatUuid(bytes) {
  const hex = Buffer.from(bytes).toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(
    16,
    20,
  )}-${hex.slice(20)}`;
}

export function deriveRequestBoundaryId(sessionId, messageIds) {
  const hash = createHash("sha1")
    .update(uuidBytes(REQUEST_BOUNDARY_NAMESPACE))
    .update(`${sessionId}\0${messageIds.join("\0")}`)
    .digest();
  const bytes = Buffer.from(hash.subarray(0, 16));
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return formatUuid(bytes);
}

function agentBoundaryKey(agent) {
  return agent?.id ?? agent?.session?.id;
}

export class PaperRagBrokerGenerationHost {
  #brokerFactory;
  #generations = new Map();
  #shutdown = false;

  constructor({ brokerFactory }) {
    if (typeof brokerFactory !== "function") {
      throw new Error("brokerFactory is required");
    }
    this.#brokerFactory = brokerFactory;
  }

  async acquire(generationId, agentId = "agent") {
    if (this.#shutdown) {
      throw new Error("broker generation host is shut down");
    }

    const key = String(generationId);
    let entry = this.#generations.get(key);
    if (entry === undefined) {
      const broker = await this.#brokerFactory(key);
      await broker.activate();
      entry = { generationId: key, broker, refCount: 0, agents: new Set() };
      this.#generations.set(key, entry);
    }

    entry.refCount += 1;
    entry.agents.add(String(agentId));
    let released = false;
    return {
      generationId: key,
      broker: entry.broker,
      release: async () => {
        if (released) {
          return;
        }
        released = true;
        entry.refCount = Math.max(0, entry.refCount - 1);
        entry.agents.delete(String(agentId));
      },
    };
  }

  diagnostics() {
    const generations = Array.from(this.#generations.values()).map((entry) => ({
      generation_id: entry.generationId,
      ref_count: entry.refCount,
      agent_count: entry.agents.size,
      private_mcp_pid: entry.broker.privateMcpPid(),
    }));
    return {
      generation_count: generations.length,
      retained_generation_count: generations.length,
      live_private_mcp_pids: generations
        .map((entry) => entry.private_mcp_pid)
        .filter((pid) => typeof pid === "number"),
      generations,
    };
  }

  async shutdown() {
    if (this.#shutdown && this.#generations.size === 0) {
      return;
    }
    this.#shutdown = true;
    const generations = Array.from(this.#generations.values());
    await Promise.all(generations.map((entry) => entry.broker.close()));
    this.#generations.clear();
  }
}

export class PaperRagNativeBroker {
  #client;
  #rawTools = new Map();
  #requestBoundaries = new Map();
  #secrets = [];
  #toolDefinitions;
  #transport;

  constructor({
    command,
    args = [],
    cwd,
    credentials,
    credentialRefs = [],
    childEnv = {},
    activePresetId = "paper-research",
    requiredPresetId = "paper-research",
    approval,
    includeWriteProbe = false,
  }) {
    this.command = command;
    this.args = args;
    this.cwd = cwd;
    this.credentials = credentials;
    this.credentialRefs = credentialRefs;
    this.childEnv = childEnv;
    this.activePresetId = activePresetId;
    this.requiredPresetId = requiredPresetId;
    this.approval = approval;
    this.includeWriteProbe = includeWriteProbe;
    this.#toolDefinitions = this.#createNativeTools();
  }

  async activate() {
    if (this.activePresetId !== this.requiredPresetId) {
      throw new Error(
        `native broker scope mismatch: expected ${this.requiredPresetId}, got ${this.activePresetId}`,
      );
    }

    const env = await this.#resolveCredentialEnv();
    this.#transport = new StdioClientTransport({
      command: this.command,
      args: this.args,
      cwd: this.cwd,
      env,
      stderr: "pipe",
    });
    this.#client = new Client({
      name: "paper-rag-native-broker",
      version: "0.0.0",
    });
    await this.#client.connect(this.#transport);

    const { tools } = await this.#client.listTools();
    this.#rawTools = new Map(tools.map((tool) => [tool.name, tool]));
  }

  async close() {
    await this.#client?.close();
    this.#client = undefined;
    this.#transport = undefined;
    this.#rawTools = new Map();
  }

  async restart() {
    await this.close();
    await this.activate();
  }

  rawToolNames() {
    return Array.from(this.#rawTools.keys());
  }

  privateMcpPid() {
    return this.#transport?.pid ?? null;
  }

  modelCatalog() {
    return Array.from(this.#toolDefinitions.values()).map((tool) => ({
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    }));
  }

  toolDefinitions() {
    return Array.from(this.#toolDefinitions.values());
  }

  finalModelCatalog() {
    return [...PRESET_LOCAL_MODEL_TOOLS, ...this.modelCatalog()];
  }

  applyAgentCreatedRestriction(agent) {
    const restrict = agent?.ctx?.tools?.restrict;
    if (typeof restrict !== "function") {
      throw new Error("agent tools restrict unavailable");
    }
    return restrict.call(agent.ctx.tools, { allow: [...INHERITED_GLOBAL_ALLOW] });
  }

  updateRequestBoundary(agent, messages = []) {
    const key = agentBoundaryKey(agent);
    if (key === undefined) {
      throw new Error("agent identity unavailable for request boundary");
    }
    const directUserIds = messages
      .filter((message) => message?.source?.kind === "user")
      .map((message) => {
        if (message?.id === undefined) {
          throw new Error("direct user message missing stable id");
        }
        return String(message.id);
      });

    if (directUserIds.length === 0) {
      return this.#requestBoundaries.get(key) ?? null;
    }

    const sessionId = agent?.session?.id ?? key;
    const boundaryId = deriveRequestBoundaryId(sessionId, directUserIds);
    this.#requestBoundaries.set(key, boundaryId);
    return boundaryId;
  }

  currentRequestBoundaryId(agent) {
    const key = agentBoundaryKey(agent);
    return key === undefined ? null : this.#requestBoundaries.get(key) ?? null;
  }

  assertPreStepToolCatalog(visibleTools) {
    const expected = catalogSignature(this.finalModelCatalog());
    const actual = catalogSignature(visibleTools);
    const expectedNames = new Set(expected.keys());
    const actualNames = new Set(actual.keys());
    const missing = [...expectedNames].filter((name) => !actualNames.has(name));
    const extra = [...actualNames].filter((name) => !expectedNames.has(name));
    const changed = [...expectedNames].filter(
      (name) => actualNames.has(name) && expected.get(name) !== actual.get(name),
    );

    if (missing.length > 0 || extra.length > 0 || changed.length > 0) {
      throw new Error(
        `model catalog invariant failed: missing=${missing.join(",") || "-"} extra=${
          extra.join(",") || "-"
        } changed=${changed.join(",") || "-"}`,
      );
    }

    return true;
  }

  /** @returns {Promise<any>} */
  async execute(name, args = {}, exec = createBrokerExec()) {
    if (this.#client === undefined) {
      throw new Error("native broker is not active");
    }
    const tool = this.#toolDefinitions.get(name);
    if (tool === undefined) {
      throw new Error(`unknown native broker tool: ${name}`);
    }
    return tool.execute(
      args,
      /** @type {any} */ ({
        ...exec,
        name,
        arguments: args,
      }),
    );
  }

  /** @returns {any[]} */
  renderForModel(name, args, value) {
    const tool = this.#toolDefinitions.get(name);
    if (tool === undefined) {
      throw new Error(`unknown native broker tool: ${name}`);
    }
    return tool.output.render(args, value);
  }

  #createNativeTools() {
    const tools = BROKER_MODEL_TOOL_NAMES.map((name) => {
      const config = brokerToolConfig(name);
      return defineTool({
        name,
        description: config.description,
        parameters: config.parameters,
        output: {
          schema: { type: "json" },
          render: (args, value) => renderPaperRagResultForModel(args, value, name),
          presentationMeta: (_args, value) => structuredContentMeta(value),
        },
        presentResult: (args, result) => presentPaperRagResult(args, result, name),
        execute: async (args, exec) => {
          if (!approvalRequired(name)) {
            return this.#callRawTool(name, args, exec);
          }
          const requestBoundaryId = this.#requireDirectHumanBoundary(exec);
          await this.#requireOneShotApproval(name, exec, approvalReasonForTool(name, args));
          return this.#callRawTool(name, args, exec, {
            request_boundary_id: requestBoundaryId,
          });
        },
      });
    });

    if (this.includeWriteProbe) {
      tools.push(
        defineTool({
        name: "write_probe",
        description: "Exercise the broker write approval path.",
        parameters: {
          note: {
            type: "string",
            required: true,
            description: "Write probe payload.",
          },
        },
        output: {
          schema: { type: "json" },
          render: renderMcpResult,
        },
        execute: async (args, exec) => {
          const requestBoundaryId = this.#requireDirectHumanBoundary(exec);
          await this.#requireOneShotApproval("write_probe", exec);
          return this.#callRawTool("write_probe", args, exec, {
            request_boundary_id: requestBoundaryId,
          });
        },
        }),
      );
    }

    return new Map(tools.map((tool) => [tool.name, tool]));
  }

  async #resolveCredentialEnv() {
    /** @type {Record<string, string>} */
    const env = { ...this.childEnv };
    const secrets = [];

    for (const rawRef of this.credentialRefs) {
      const ref = credentialRef(rawRef);
      const description = await this.credentials?.describe?.(ref);
      if (description?.configured === false) {
        continue;
      }

      const resolved = await this.credentials?.resolve?.(ref);
      if (typeof resolved?.value !== "string" || resolved.value.length === 0) {
        continue;
      }

      env[ref] = resolved.value;
      secrets.push(resolved.value);
    }

    if (!env.OPENAI_API_KEY && env.DEEPSEEK_API_KEY) {
      env.OPENAI_API_KEY = env.DEEPSEEK_API_KEY;
    }
    if (!env.DEEPSEEK_API_KEY && env.OPENAI_API_KEY) {
      env.DEEPSEEK_API_KEY = env.OPENAI_API_KEY;
    }
    if (!env.OPENAI_BASE_URL && env.DEEPSEEK_BASE_URL) {
      env.OPENAI_BASE_URL = env.DEEPSEEK_BASE_URL;
    }
    if (!env.DEEPSEEK_BASE_URL && env.OPENAI_BASE_URL) {
      env.DEEPSEEK_BASE_URL = env.OPENAI_BASE_URL;
    }

    this.#secrets = secrets;
    return env;
  }

  #requireDirectHumanBoundary(exec) {
    const requestBoundaryId = this.currentRequestBoundaryId(exec?.agent);
    if (requestBoundaryId === null) {
      const error = /** @type {Error & { code?: string }} */ (
        new Error("DIRECT_USER_AUTHORITY_REQUIRED")
      );
      error.code = "DIRECT_USER_AUTHORITY_REQUIRED";
      throw error;
    }
    return requestBoundaryId;
  }

  async #requireOneShotApproval(
    toolName,
    exec,
    reason = `${toolName} requires one-shot write approval`,
  ) {
    if (this.approval?.request === undefined || exec?.agent === undefined) {
      throw new Error(`approval unavailable for ${toolName}`);
    }

    const outcome = await this.approval.request({
      agent: exec.agent,
      toolName,
      callId: exec?.callId,
      reason,
      signal: exec?.signal,
    });
    if (outcome !== APPROVAL_ALLOW_ONCE) {
      throw new Error(`approval ${outcome}`);
    }
  }

  async #callRawTool(rawName, args, exec, paperRagExtra = {}) {
    if (this.#client === undefined) {
      throw new Error("native broker is not active");
    }
    if (!this.#rawTools.has(rawName)) {
      throw new Error(`private MCP tool not found: ${rawName}`);
    }

    const result = await this.#client.request(
      {
        method: "tools/call",
        params: {
          name: rawName,
          arguments: args,
          _meta: {
            paper_rag: paperRagMeta(exec, paperRagExtra),
          },
        },
      },
      CallToolResultSchema,
      mcpRequestOptionsForTool(rawName, exec?.signal),
    );
    const safeResult = redactResult(result, this.#secrets);
    if (safeResult.isError) {
      throw new Error(`private MCP tool ${rawName} returned an error`);
    }
    return safeResult;
  }
}

function structuredContentMeta(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  return /** @type {any} */ (value).structuredContent;
}
