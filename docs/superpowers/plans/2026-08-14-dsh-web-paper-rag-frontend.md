# DSH Web Paper RAG Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DSH Web the primary Paper RAG frontend by exposing the full research workflow through broker-owned native tools, portable result cards, evidence-safe answer rendering, and approval-gated writes.

**Architecture:** DSH Web remains the browser/chat shell. The native broker exposes the selected Paper RAG research tools, converts MCP envelopes into portable card data plus bounded Markdown fallback, and keeps write approval/request-boundary handling outside model-visible arguments. The Python MCP layer remains the kernel contract owner for discovery, ingestion, QA, comparison, sections, and artifact delivery.

**Tech Stack:** Node.js ESM, `@deepseek-ai/dsh-tools` `defineTool`/`presentResult`, Vitest, Python MCP registry, pytest, `scripts/migration_gate.py`, `scripts/secret_scan.py`, `deepseek-v4-flash`.

## Global Constraints

- Read the current checkout before changing behavior; treat current files as authoritative.
- Commit this implementation plan before implementation code.
- Preserve the DSH runtime shape: `DSH Web -> Paper Research preset -> Native Broker -> private Paper RAG MCP -> src/paper_rag`.
- Do not restore `integrations/deer-flow/` or `scripts/deerflow_smoke.py`.
- Use DSH Web portable cards: stable structured data plus bounded Markdown fallback.
- Use native DSH `presentResult` only as generic card presentation; do not depend on private Web UI internals.
- Cover `paper_discover -> discovery_run_get/select -> approval -> discovery_candidate_ingest or paper_ingest -> paper_qa/paper_compare/paper_section -> paper_deliver`.
- Card types required: Corpus Status, Discovery Candidates, Ingest Receipt, Evidence Answer, Artifact Delivery.
- Write tools requiring approval: `paper_ingest`, `discovery_candidate_ingest`, `paper_deliver`.
- Discovery candidates, web snippets, chat history, and memory are not Paper RAG answer evidence.
- Paper claims must cite indexed chunks or surface a weak/no-evidence state.
- Keep `deepseek-v4-flash`; do not switch to a pro model.
- Do not commit `.env`, API keys, `data/index`, runtime credentials, real PDFs, temporary live-smoke data, or secrets.
- Do not run live smoke against the real paper library without explicit user approval; default smoke uses isolated runtime/data paths.
- Required final validation includes unit tests, broker tests, MCP contract tests, DSH headless workflow smoke, migration validators, secret scan, and clean git status.

---

## Current State Map

- `docs/superpowers/specs/2026-08-14-dsh-web-paper-rag-frontend-design.md` defines the approved frontend design.
- `integrations/deepseek-harness/src/broker.mjs` currently exposes only readonly native tools through `READONLY_TOOL_NAMES`.
- `integrations/deepseek-harness/src/paper-rag-native-broker-plugin.mjs` defaults `PAPER_RAG_MCP_TOOLSET` to `readonly`.
- `src/paper_rag/mcp/registry.py` already supports `research` toolset with `paper_discover`, `discovery_run_get`, `paper_ingest`, `discovery_candidate_ingest`, and `paper_deliver`.
- `src/paper_rag/mcp/presenters.py` already returns bounded MCP envelopes with `structuredContent` and model-facing text.
- `integrations/deepseek-harness/node_modules/@deepseek-ai/dsh-tools/lib/types/index.d.ts` exposes `presentResult(args, result)` and generic UI result cards.
- `scripts/migration_gate.py` has live G1/G2 runners, but LIVE-002 through LIVE-004 currently call Python MCP directly rather than a DSH headless chat workflow.

## File Structure

- Create `integrations/deepseek-harness/src/paper-rag-tool-catalog.mjs`: broker-visible tool names, schemas, descriptions, exposure classes, approval side-effect summaries.
- Create `integrations/deepseek-harness/src/paper-rag-cards.mjs`: portable card projection, Markdown fallback rendering, and generic `presentResult` view generation.
- Modify `integrations/deepseek-harness/src/broker.mjs`: use the catalog, expose discovery/write tools, approval-gate write calls, and attach card render/presentation functions.
- Modify `integrations/deepseek-harness/src/paper-rag-native-broker-plugin.mjs`: make the Paper Research preset default to the `research` MCP toolset unless explicitly overridden.
- Modify `integrations/deepseek-harness/fixtures/private-mcp-server.mjs` and `fixtures/private_mcp_server.py`: add fixture research tools used by broker tests.
- Modify `integrations/deepseek-harness/tests/broker.spec.mjs`, `broker-probe.spec.mjs`, `composition.spec.mjs`, and `paper-rag-headless-runner.spec.mjs`: assert full catalog, approval, cards, and headless workflow evidence.
- Create `integrations/deepseek-harness/tests/paper-rag-cards.spec.mjs`: focused card projection tests.
- Create `tests/test_mcp_frontend_contract.py`: Python MCP contract tests for fields consumed by cards.
- Modify `integrations/deepseek-harness/presets/paper-research/agent.cordis.yml`: strengthen guided workflow, evidence, and write-approval persona.
- Modify `integrations/deepseek-harness/src/paper-rag-headless-runner.mjs`: optionally emit a JSON summary of tool calls/cards when configured for smoke validation.
- Modify `scripts/migration_gate.py` and `specs/20260813-deepseek-harness-migration/test/test-manifest.json`: add an isolated DSH frontend workflow smoke case and validator wiring.
- Modify `integrations/deepseek-harness/README.md`: document DSH Web as the Paper RAG frontend and the portable card contract.

## Task 1: Portable Card Projection Module

**Files:**
- Create: `integrations/deepseek-harness/src/paper-rag-cards.mjs`
- Create: `integrations/deepseek-harness/tests/paper-rag-cards.spec.mjs`

**Interfaces:**
- Produces: `createPortableCard(toolName: string, args: object, structuredContent: object): object`
- Produces: `cardTypeForTool(toolName: string): string | undefined`
- Produces: `renderPortableCardMarkdown(card: object): string`
- Produces: `renderPaperRagResultForModel(args: object, value: object): Array<{type: "text", text: string}>`
- Produces: `presentPaperRagResult(args: object, result: {content: Array<object>, isError: boolean, meta?: object}): object | undefined`
- Consumes: MCP result shape `{ structuredContent: { ok, tool, data, error, warnings, evidence_role, trace_id } }`

- [ ] **Step 1: Write failing card projection tests**

Create `integrations/deepseek-harness/tests/paper-rag-cards.spec.mjs` with these assertions:

```js
import { describe, expect, test } from "vitest";

import {
  createPortableCard,
  presentPaperRagResult,
  renderPaperRagResultForModel,
  renderPortableCardMarkdown,
} from "../src/paper-rag-cards.mjs";

describe("Paper RAG portable cards", () => {
  test("renders discovery candidates as candidate-only evidence", () => {
    const structuredContent = {
      ok: true,
      tool: "paper_discover",
      evidence_role: "discovery_only",
      data: {
        run: { id: 7, topic: "agentic rag" },
        candidates: [
          {
            id: 11,
            title: "Agentic RAG",
            source: "arxiv",
            year: 2026,
            rank: 1,
            rank_reason: "matches retrieval loop",
            evidence_role: "discovery_only_not_answer_evidence",
          },
        ],
      },
      warnings: [],
    };

    const card = createPortableCard("paper_discover", { topic: "agentic rag" }, structuredContent);
    const markdown = renderPortableCardMarkdown(card);

    expect(card.type).toBe("discovery_candidates");
    expect(card.title).toBe("Discovery Candidates");
    expect(card.items[0]).toMatchObject({ id: 11, title: "Agentic RAG", source: "arxiv" });
    expect(markdown).toContain("Discovery Candidates");
    expect(markdown).toContain("Candidate-only; not Paper RAG answer evidence");
    expect(markdown.length).toBeLessThan(1800);
  });

  test("renders evidence answers with citations and abstain state", () => {
    const structuredContent = {
      ok: true,
      tool: "paper_qa",
      evidence_role: "indexed_chunks",
      trace_id: "trace-1",
      data: {
        answer: "The method uses iterative retrieval. [chunk:c1]",
        citations: ["c1"],
        chunks: [{ chunk_id: "c1", paper_id: "paper-1", title: "Agentic RAG", text: "iterative retrieval" }],
        abstain: { decision: "answer" },
      },
      warnings: [],
    };

    const card = createPortableCard("paper_qa", { question: "method?" }, structuredContent);
    const markdown = renderPortableCardMarkdown(card);

    expect(card.type).toBe("evidence_answer");
    expect(card.fields.citation_count).toBe(1);
    expect(markdown).toContain("Evidence Answer");
    expect(markdown).toContain("citations=1");
    expect(markdown).toContain("trace-1");
  });

  test("renders write receipts with side-effect language and no request boundary leakage", () => {
    const structuredContent = {
      ok: true,
      tool: "paper_deliver",
      evidence_role: "artifact",
      data: {
        artifact: {
          artifact_id: "artifact-1",
          path: "/repo/data/artifacts/artifact-1",
          manifest_path: "/repo/data/artifacts/artifact-1/manifest.json",
        },
        format: "pdf",
        paper_count: 1,
      },
      warnings: [],
    };

    const card = createPortableCard("paper_deliver", { format: "pdf", paper_ids: ["p1"] }, structuredContent);
    const markdown = renderPortableCardMarkdown(card);

    expect(card.type).toBe("artifact_delivery");
    expect(markdown).toContain("Artifact Delivery");
    expect(markdown).toContain("manifest.json");
    expect(markdown).not.toContain("request_boundary_id");
  });

  test("projects model fallback and generic DSH result card", () => {
    const value = {
      structuredContent: {
        ok: true,
        tool: "paper_status",
        evidence_role: "metadata",
        data: { sqlite: { paper_count: 2, chunk_count: 9 }, llm: { chat_model: "deepseek-v4-flash" } },
        warnings: [],
      },
    };

    const content = renderPaperRagResultForModel({}, value);
    const view = presentPaperRagResult({}, { content, isError: false, meta: value.structuredContent });

    expect(content[0].text).toContain("Corpus Status");
    expect(content[0].text).toContain("deepseek-v4-flash");
    expect(view).toMatchObject({ card: "generic", title: "Corpus Status" });
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
pnpm --dir integrations/deepseek-harness exec vitest run tests/paper-rag-cards.spec.mjs
```

Expected: fail with a module-not-found error for `../src/paper-rag-cards.mjs`.

- [ ] **Step 3: Implement the card module**

Create `integrations/deepseek-harness/src/paper-rag-cards.mjs` with this shape:

```js
const MAX_CARD_TEXT = 1800;

const CARD_BY_TOOL = Object.freeze({
  paper_status: "corpus_status",
  paper_list: "corpus_status",
  paper_discover: "discovery_candidates",
  discovery_run_get: "discovery_candidates",
  paper_ingest: "ingest_receipt",
  discovery_candidate_ingest: "ingest_receipt",
  paper_qa: "evidence_answer",
  paper_compare: "evidence_answer",
  paper_section: "evidence_answer",
  paper_deliver: "artifact_delivery",
});

export function createPortableCard(toolName, args = {}, structuredContent = {}) {
  const data = structuredContent.data ?? {};
  const type = CARD_BY_TOOL[toolName] ?? "paper_rag_result";
  const base = {
    schema_version: 1,
    type,
    tool: toolName,
    title: titleFor(type),
    ok: structuredContent.ok === true,
    evidence_role: structuredContent.evidence_role ?? "none",
    trace_id: structuredContent.trace_id ?? null,
    warnings: Array.isArray(structuredContent.warnings) ? structuredContent.warnings : [],
    fields: {},
    items: [],
  };
  return populateCard(base, args, data, structuredContent);
}

export function cardTypeForTool(toolName) {
  return CARD_BY_TOOL[toolName];
}

export function renderPaperRagResultForModel(args, value) {
  const structured = value?.structuredContent ?? value ?? {};
  const toolName = structured.tool ?? "paper_rag";
  const card = createPortableCard(toolName, args, structured);
  return [{ type: "text", text: renderPortableCardMarkdown(card) }];
}

export function presentPaperRagResult(args, result) {
  const structured = result?.meta;
  if (structured === undefined || structured === null || typeof structured !== "object") return undefined;
  const card = createPortableCard(structured.tool ?? "paper_rag", args, structured);
  return {
    card: "generic",
    title: card.title,
    content: [{ type: "text", text: renderPortableCardMarkdown(card) }],
  };
}
```

Include helper functions `titleFor`, `populateCard`, `renderPortableCardMarkdown`, `bounded`, and small per-card renderers. The Markdown output must avoid `request_boundary_id`, raw `_meta`, environment variable values, and base64 payload fields.

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
pnpm --dir integrations/deepseek-harness exec vitest run tests/paper-rag-cards.spec.mjs
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add integrations/deepseek-harness/src/paper-rag-cards.mjs integrations/deepseek-harness/tests/paper-rag-cards.spec.mjs
git commit -m "feat: add paper rag portable cards"
```

## Task 2: Broker Research Tool Catalog And Write Approval

**Files:**
- Create: `integrations/deepseek-harness/src/paper-rag-tool-catalog.mjs`
- Modify: `integrations/deepseek-harness/src/broker.mjs`
- Modify: `integrations/deepseek-harness/src/paper-rag-native-broker-plugin.mjs`
- Modify: `integrations/deepseek-harness/fixtures/private-mcp-server.mjs`
- Modify: `integrations/deepseek-harness/fixtures/private_mcp_server.py`
- Modify: `integrations/deepseek-harness/tests/broker.spec.mjs`
- Modify: `integrations/deepseek-harness/src/broker-probe.mjs`

**Interfaces:**
- Consumes from Task 1: `renderPaperRagResultForModel`, `presentPaperRagResult`
- Produces: `BROKER_MODEL_TOOL_NAMES: readonly string[]`
- Produces: `BROKER_WRITE_TOOL_NAMES: readonly string[]`
- Produces: `brokerToolConfig(name: string): { name, description, parameters, approvalRequired }`
- Produces: `approvalReasonForTool(name: string, args: object): string`

- [ ] **Step 1: Write failing broker catalog and approval tests**

Modify `integrations/deepseek-harness/tests/broker.spec.mjs`:

```js
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

test("exposes the Paper Research model catalog without private MCP names", async () => {
  const broker = await startBroker({ childEnv: { PAPER_RAG_MCP_TOOLSET: "research" } });

  expect(broker.modelCatalog().map((tool) => tool.name).sort()).toEqual(MODEL_TOOL_NAMES);
  expect(broker.modelCatalog().some((tool) => tool.name.startsWith("mcp__"))).toBe(false);
  expect(broker.modelCatalog().some((tool) => tool.name === "wiki_generate")).toBe(false);
  expect(broker.modelCatalog().some((tool) => tool.name === "export_bibtex")).toBe(false);
});

test("approval-gated Paper RAG writes require a direct user boundary", async () => {
  const approvalCalls = [];
  const broker = await startBroker({
    childEnv: { PAPER_RAG_MCP_TOOLSET: "research" },
    approval: approval("allowed-once", approvalCalls),
  });
  const exec = createBrokerExec({ agentId: "agent-write-denied", callId: "call-write-denied" });

  await expect(
    broker.execute("paper_ingest", { arxiv_id: "2601.00001" }, exec),
  ).rejects.toThrow("DIRECT_USER_AUTHORITY_REQUIRED");
  expect(approvalCalls).toHaveLength(0);
});

test("approval-gated Paper RAG writes send side-effect reason and hidden boundary", async () => {
  const approvalCalls = [];
  const auditPath = await newAuditPath();
  const broker = await startBroker({
    childEnv: { PAPER_RAG_PRIVATE_AUDIT_PATH: auditPath, PAPER_RAG_MCP_TOOLSET: "research" },
    approval: approval("allowed-once", approvalCalls),
  });
  const exec = createBrokerExec({ agentId: "agent-write-ok", sessionId: "session-write-ok", callId: "call-write-ok" });
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
  const audit = (await readAuditLines(auditPath)).find((line) => line.tool_name === "discovery_candidate_ingest");
  expect(audit.received_meta.paper_rag.request_boundary_id).toBe(boundary);
});
```

- [ ] **Step 2: Run broker tests and verify they fail**

Run:

```bash
pnpm --dir integrations/deepseek-harness exec vitest run tests/broker.spec.mjs
```

Expected: fail because research tools are not in the broker catalog and fixture MCP servers do not list them.

- [ ] **Step 3: Implement the tool catalog**

Create `integrations/deepseek-harness/src/paper-rag-tool-catalog.mjs` with:

```js
export const BROKER_READ_TOOL_NAMES = Object.freeze([
  "paper_status",
  "paper_list",
  "paper_search",
  "paper_qa",
  "paper_section",
  "paper_compare",
  "wiki_lookup",
]);

export const BROKER_DISCOVERY_TOOL_NAMES = Object.freeze([
  "paper_discover",
  "discovery_run_get",
]);

export const BROKER_WRITE_TOOL_NAMES = Object.freeze([
  "paper_ingest",
  "discovery_candidate_ingest",
  "paper_deliver",
]);

export const BROKER_MODEL_TOOL_NAMES = Object.freeze([
  ...BROKER_READ_TOOL_NAMES,
  ...BROKER_DISCOVERY_TOOL_NAMES,
  ...BROKER_WRITE_TOOL_NAMES,
]);

export function approvalRequired(name) {
  return BROKER_WRITE_TOOL_NAMES.includes(name);
}

export function approvalReasonForTool(name, args = {}) {
  if (name === "paper_ingest") return `paper_ingest writes to the configured Paper RAG corpus; source=${sourceForIngest(args)}`;
  if (name === "discovery_candidate_ingest") return `discovery_candidate_ingest writes approved candidates to the configured Paper RAG corpus; candidate_ids=${(args.candidate_ids ?? []).join(",")}`;
  if (name === "paper_deliver") return `paper_deliver writes artifact files under PAPER_RAG_ARTIFACT_ROOT; format=${args.format} paper_ids=${(args.paper_ids ?? []).join(",")}`;
  return `${name} requires one-shot write approval`;
}
```

Also define `brokerToolConfig(name)` with descriptions and parameter schemas copied from current `broker.mjs` and extended for:

```js
paper_discover: { topic, max_candidates, sources }
discovery_run_get: { run_id }
paper_ingest: { arxiv_id, pdf_url, pdf_path, title_hint, force }
discovery_candidate_ingest: { candidate_ids, force }
paper_deliver: { format, paper_ids, title, options }
```

- [ ] **Step 4: Wire the broker to use the catalog and gate writes**

Modify `integrations/deepseek-harness/src/broker.mjs`:

```js
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
```

Replace `READONLY_TOOL_NAMES.map(...)` in `#createNativeTools()` with `BROKER_MODEL_TOOL_NAMES.map(...)`. For each tool:

```js
const config = brokerToolConfig(name);
defineTool({
  name,
  description: config.description,
  parameters: config.parameters,
  output: {
    schema: { type: "json" },
    render: renderPaperRagResultForModel,
    presentationMeta: (_args, value) => value?.structuredContent,
  },
  presentResult: presentPaperRagResult,
  execute: async (args, exec) => {
    if (!approvalRequired(name)) return this.#callRawTool(name, args, exec);
    const requestBoundaryId = this.#requireDirectHumanBoundary(exec);
    await this.#requireOneShotApproval(name, exec, approvalReasonForTool(name, args));
    return this.#callRawTool(name, args, exec, { request_boundary_id: requestBoundaryId });
  },
});
```

Change `#requireOneShotApproval(toolName, exec)` to accept `reason`:

```js
async #requireOneShotApproval(toolName, exec, reason = `${toolName} requires one-shot write approval`) {
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
  if (outcome !== APPROVAL_ALLOW_ONCE) throw new Error(`approval ${outcome}`);
}
```

Keep the `includeWriteProbe` branch intact for compatibility.

- [ ] **Step 5: Default the Paper Research plugin to research toolset**

Modify `integrations/deepseek-harness/src/paper-rag-native-broker-plugin.mjs`:

```js
toolset: process.env.PAPER_RAG_MCP_TOOLSET ?? "research",
```

Leave `buildPaperRagMcpChildEnv()` default as `readonly` for direct tests that intentionally request readonly.

- [ ] **Step 6: Extend MCP fixtures with research tool stubs**

In both fixture servers, add tool list entries and call responses for `paper_discover`, `discovery_run_get`, `paper_ingest`, `discovery_candidate_ingest`, and `paper_deliver`. The JS fixture response for discovery should include:

```js
{
  ok: true,
  tool: request.params.name,
  data: {
    run: { id: 7, topic: args.topic ?? "fixture topic" },
    candidates: [{ id: 11, title: "Fixture Candidate", source: "fixture", rank: 1, evidence_role: "discovery_only_not_answer_evidence" }],
    count: 1,
  },
  evidence_role: "discovery_only",
  warnings: [],
}
```

The JS fixture response for write tools should increment `writeCallCount` and include `ok: true`, `tool`, `data`, `evidence_role`, and `warnings`.

- [ ] **Step 7: Update broker probe expectations**

Modify `integrations/deepseek-harness/src/broker-probe.mjs` so `READONLY_MODEL_TOOL_NAMES` becomes the sorted full Paper Research model catalog. Update report evidence names from readonly to Paper Research model tools.

- [ ] **Step 8: Run focused broker tests**

Run:

```bash
pnpm --dir integrations/deepseek-harness exec vitest run tests/broker.spec.mjs tests/broker-probe.spec.mjs
```

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

```bash
git add integrations/deepseek-harness/src/broker.mjs integrations/deepseek-harness/src/paper-rag-native-broker-plugin.mjs integrations/deepseek-harness/src/paper-rag-tool-catalog.mjs integrations/deepseek-harness/src/broker-probe.mjs integrations/deepseek-harness/fixtures/private-mcp-server.mjs integrations/deepseek-harness/fixtures/private_mcp_server.py integrations/deepseek-harness/tests/broker.spec.mjs integrations/deepseek-harness/tests/broker-probe.spec.mjs
git commit -m "feat: expose paper rag research tools in dsh"
```

## Task 3: MCP Frontend Contract Tests

**Files:**
- Create: `tests/test_mcp_frontend_contract.py`
- Modify only if a test proves a missing field: `src/paper_rag/mcp/registry.py` or `src/paper_rag/mcp/presenters.py`

**Interfaces:**
- Consumes: `paper_rag.mcp.registry.call_tool(name, args, ctx)`
- Produces test proof that MCP envelopes contain the fields used by portable cards.

- [ ] **Step 1: Write failing or proving MCP contract tests**

Create `tests/test_mcp_frontend_contract.py`:

```python
from __future__ import annotations

import importlib
from pathlib import Path


def _ctx(tmp_path: Path, *, boundary: str | None = "boundary-1"):
    from paper_rag.mcp.context import McpRequestContext, McpServerConfig

    return McpRequestContext(
        config=McpServerConfig(
            toolset="research",
            actor_id="system",
            artifact_root=tmp_path / "artifacts",
            import_root=tmp_path / "imports",
        ),
        conversation_id="dsh-session-frontend",
        tool_call_id="call-frontend",
        request_boundary_id=boundary,
    )


def test_discovery_contract_has_candidate_card_fields(monkeypatch, tmp_path):
    from paper_rag.discovery import runner
    from paper_rag.mcp.registry import call_tool

    monkeypatch.setattr(
        runner,
        "run_discovery",
        lambda topic, user_id, source_names, max_candidates: {
            "run": {"id": 7, "topic": topic},
            "trace": {"provider": "fixture"},
            "candidates": [
                {"id": 11, "title": "Candidate", "source": "arxiv", "rank": 1, "rank_reason": "close match"}
            ],
        },
    )

    structured = call_tool("paper_discover", {"topic": "agentic rag"}, _ctx(tmp_path))["structuredContent"]

    assert structured["ok"] is True
    assert structured["tool"] == "paper_discover"
    assert structured["evidence_role"] == "discovery_only"
    assert structured["data"]["run"]["id"] == 7
    assert structured["data"]["candidates"][0]["id"] == 11
    assert structured["data"]["candidates"][0]["evidence_role"] == "discovery_only_not_answer_evidence"


def test_answer_contract_has_citations_chunks_and_abstain(monkeypatch, tmp_path):
    from paper_rag.mcp.registry import call_tool
    from paper_rag.tools import paper_qa as paper_qa_module

    monkeypatch.setattr(
        paper_qa_module,
        "paper_qa",
        lambda payload: {
            "answer": "Uses iterative retrieval. [chunk:c1]",
            "citations": ["c1"],
            "chunks": [{"chunk_id": "c1", "paper_id": "p1", "text": "iterative retrieval"}],
            "trace": {"trace_id": "trace-front", "abstain": {"decision": "answer"}},
        },
    )

    structured = call_tool("paper_qa", {"question": "method?", "paper_ids": ["p1"]}, _ctx(tmp_path))["structuredContent"]

    assert structured["ok"] is True
    assert structured["evidence_role"] == "indexed_chunks"
    assert structured["trace_id"] == "trace-front"
    assert structured["data"]["citations"] == ["c1"]
    assert structured["data"]["chunks"][0]["chunk_id"] == "c1"
    assert structured["data"]["abstain"]["decision"] == "answer"


def test_write_contracts_include_receipt_and_artifact_metadata(monkeypatch, tmp_path):
    deliver_dispatch = importlib.import_module("paper_rag.deliver.dispatch")
    from paper_rag.discovery import runner
    from paper_rag.mcp.registry import call_tool

    monkeypatch.setattr(
        runner,
        "ingest_candidate",
        lambda candidate_id, user_id, force=False: {
            "candidate_id": candidate_id,
            "paper_id": f"paper-{candidate_id}",
            "status": "ingested",
            "n_chunks": 4,
        },
    )
    monkeypatch.setattr(
        deliver_dispatch,
        "dispatch",
        lambda format, paper_ids, title=None, options=None, user_id="system": deliver_dispatch.DeliverableResult(
            format=format,
            filename="front.md",
            content_bytes=b"# Frontend Contract\n",
            content_type="text/markdown; charset=utf-8",
            metadata={"n_citations": 1},
        ),
    )

    ingest = call_tool("discovery_candidate_ingest", {"candidate_ids": [11]}, _ctx(tmp_path))["structuredContent"]
    deliver = call_tool(
        "paper_deliver",
        {"format": "markdown_survey", "paper_ids": ["paper-11"], "title": "Frontend Contract"},
        _ctx(tmp_path),
    )["structuredContent"]

    assert ingest["ok"] is True
    assert ingest["data"]["results"][0]["paper_id"] == "paper-11"
    assert ingest["data"]["results"][0]["status"] == "ingested"
    assert deliver["ok"] is True
    assert deliver["evidence_role"] == "artifact"
    assert deliver["data"]["artifact"]["manifest_path"].endswith("manifest.json")
    assert "content_base64" not in str(deliver)
```

- [ ] **Step 2: Run the new MCP contract test**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_mcp_frontend_contract.py
```

Expected: PASS if current MCP envelopes already satisfy the frontend contract. If a specific assertion fails, change only the registry or presenter field named by that assertion.

- [ ] **Step 3: Run existing MCP focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_mcp_contract.py tests/test_mcp_tools.py tests/test_mcp_security.py tests/test_mcp_artifacts.py tests/test_mcp_operations.py tests/test_dsh_parity.py tests/test_mcp_frontend_contract.py
```

Expected: PASS.

- [ ] **Step 4: Commit Task 3**

```bash
git add tests/test_mcp_frontend_contract.py src/paper_rag/mcp/registry.py src/paper_rag/mcp/presenters.py
git commit -m "test: cover mcp frontend contracts"
```

If `src/paper_rag/mcp/registry.py` and `src/paper_rag/mcp/presenters.py` did not change, omit them from `git add`.

## Task 4: Paper Research Preset And Composition Tests

**Files:**
- Modify: `integrations/deepseek-harness/presets/paper-research/agent.cordis.yml`
- Modify: `integrations/deepseek-harness/tests/composition.spec.mjs`
- Modify: `integrations/deepseek-harness/README.md`

**Interfaces:**
- Consumes: broker-visible tool names from Task 2.
- Produces: preset instructions that guide discover, selection, approval, evidence answer, and delivery.

- [ ] **Step 1: Write preset composition assertions**

Modify `integrations/deepseek-harness/tests/composition.spec.mjs` in the preset sync test:

```js
const syncedAgent = await readFile(join(result.destDir, "agent.cordis.yml"), "utf8");
expect(syncedAgent).toContain("paper_discover");
expect(syncedAgent).toContain("discovery_candidate_ingest");
expect(syncedAgent).toContain("paper_deliver");
expect(syncedAgent).toContain("Candidate results are not Paper RAG answer evidence");
expect(syncedAgent).toContain("deepseek-v4-flash");
```

- [ ] **Step 2: Run the composition test and verify it fails**

Run:

```bash
pnpm --dir integrations/deepseek-harness exec vitest run tests/composition.spec.mjs
```

Expected: fail because the current persona does not name the full guided workflow or flash model.

- [ ] **Step 3: Update the Paper Research persona**

Replace the persona text in `integrations/deepseek-harness/presets/paper-research/agent.cordis.yml` with:

```yaml
      You are a Paper RAG research assistant running in the Paper Research preset on deepseek-v4-flash.
      Use Paper RAG tools for claims about indexed papers.
      Guide research through: paper_discover, candidate selection, approval, discovery_candidate_ingest or paper_ingest, paper_qa or paper_compare or paper_section, and paper_deliver when a deliverable is requested.
      Candidate results are not Paper RAG answer evidence. Web snippets, chat history, and memory are not Paper RAG answer evidence.
      Paper claims must cite indexed chunks returned by Paper RAG tools. If indexed evidence is missing or weak, say that clearly and ask whether to discover or ingest papers.
      Before write tools, summarize the side effects and rely on the approval gate for paper_ingest, discovery_candidate_ingest, and paper_deliver.
      Ask the user one concise question when scope, paper identity, candidate selection, or write intent is unclear.
```

- [ ] **Step 4: Update integration README**

Add a section to `integrations/deepseek-harness/README.md`:

```markdown
## Paper RAG Frontend

DSH Web is the Paper RAG frontend. The `Paper Research` preset exposes broker-owned native tools for corpus status, discovery, ingestion, evidence QA, comparison, sections, and artifact delivery. Tool results use portable cards: structured MCP envelopes plus bounded Markdown fallback, with DSH generic result cards when the host renders `presentResult`.

Write tools (`paper_ingest`, `discovery_candidate_ingest`, `paper_deliver`) require one-shot approval and a direct user request boundary. Discovery candidates are candidate-only metadata and must not be cited as answer evidence.
```

- [ ] **Step 5: Run composition tests**

Run:

```bash
pnpm --dir integrations/deepseek-harness exec vitest run tests/composition.spec.mjs
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add integrations/deepseek-harness/presets/paper-research/agent.cordis.yml integrations/deepseek-harness/tests/composition.spec.mjs integrations/deepseek-harness/README.md
git commit -m "docs: make dsh web the paper rag frontend"
```

## Task 5: DSH Headless Workflow Smoke Evidence

**Files:**
- Modify: `integrations/deepseek-harness/src/paper-rag-headless-runner.mjs`
- Modify: `integrations/deepseek-harness/tests/paper-rag-headless-runner.spec.mjs`
- Modify: `scripts/migration_gate.py`
- Modify: `specs/20260813-deepseek-harness-migration/test/test-manifest.json`

**Interfaces:**
- Consumes: DSH session events from the mounted `paper-research` preset.
- Produces: a smoke report proving DSH headless can run through the frontend workflow with isolated data paths.

- [ ] **Step 1: Write headless summary tests**

Extend `integrations/deepseek-harness/tests/paper-rag-headless-runner.spec.mjs`:

```js
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
```

- [ ] **Step 2: Run the headless runner tests and verify failure**

Run:

```bash
pnpm --dir integrations/deepseek-harness exec vitest run tests/paper-rag-headless-runner.spec.mjs
```

Expected: fail because `summarize` does not accept `includeWorkflow` or emit `tool_calls` and `cards`.

- [ ] **Step 3: Extend headless summarization**

Modify `summarize(events, firstSeq, options = {})` in `paper-rag-headless-runner.mjs`:

```js
import { cardTypeForTool } from "./paper-rag-cards.mjs";

export function summarize(events, firstSeq, options = {}) {
  let started = false;
  let text = "";
  let reason;
  const toolCalls = [];
  const cards = [];
  for (const event of events) {
    if (event.seq < firstSeq) continue;
    if (event.type === "turn/start") {
      started = true;
      continue;
    }
    if (!started) continue;
    if (event.type === "tool/call") {
      const name = event.data?.name ?? event.data?.toolName;
      if (typeof name === "string") toolCalls.push(name);
    }
    if (event.type === "tool/result") {
      const structured = event.data?.result?.structuredContent ?? event.data?.result?.meta;
      const cardType = cardTypeForTool(structured?.tool ?? event.data?.name);
      if (cardType !== undefined) cards.push(cardType);
    }
    if (event.type === "assistant/message") {
      const joined = event.data.message.content
        .filter((block) => block.type === "text")
        .map((block) => block.text)
        .join("");
      if (joined !== "") text = joined;
    }
    if (event.type === "turn/end") reason = event.data.reason;
  }
  return options.includeWorkflow ? { text, reason, tool_calls: toolCalls, cards } : { text, reason };
}
```

When `rawConfig.reportJson === true`, make `run()` write JSON to stdout:

```js
io.stdout.write(`${JSON.stringify(outcome, null, 2)}\n`);
```

Otherwise keep the current plain text output.

- [ ] **Step 4: Add migration live case for isolated DSH frontend smoke**

In `scripts/migration_gate.py`, add case `LIVE-005` with gate `G2`. It should:

```python
def run_live005_dsh_frontend_workflow(repo_root: Path, env_source: dict[str, str], config_env: str | None = None) -> dict[str, Any]:
    _require_live_g2_flash_env(env_source, "LIVE-005")
    workspace = _prepare_live_g2_workspace(repo_root, _live_g2_default_work_root(repo_root), reset=False)
    isolation = _assert_live_g2_workspace_isolated(repo_root, workspace)
    env = _live_g2_env_for(repo_root, workspace, env_source)
    summary = _run_live005_headless_workflow(repo_root, workspace, env)
    checks = [
        {"id": "dsh-headless-used-paper-research", "status": "PASS" if summary.get("preset") == "paper-research" else "FAIL", "detail": str(summary.get("preset"))},
        {"id": "dsh-headless-workflow-tools", "status": "PASS" if _has_live005_tools(summary) else "FAIL", "detail": ",".join(summary.get("tool_calls", []))},
        {"id": "dsh-headless-portable-cards", "status": "PASS" if _has_live005_cards(summary) else "FAIL", "detail": ",".join(summary.get("cards", []))},
        {"id": "dsh-headless-isolated", "status": "PASS", "detail": json.dumps(isolation, sort_keys=True)},
    ]
    return {"checks": checks, "metrics": {"tool_calls": len(summary.get("tool_calls", [])), "cards": len(summary.get("cards", []))}, "summary": summary}
```

The helper `_run_live005_headless_workflow` should invoke the DSH binary with `live-headless.patch.yml`, isolated `DSH_HOME`, `PAPER_RAG_MCP_TOOLSET=research`, and a prompt that asks for discovery, approved isolated candidate ingestion, evidence answer, and an artifact. The report path is `data/index/migration-gates/live/LIVE-005.json`.

- [ ] **Step 5: Update the manifest live cases**

Add this entry to `specs/20260813-deepseek-harness-migration/test/test-manifest.json`:

```json
{
  "id": "LIVE-005",
  "gate": "G2",
  "runner": ".venv/bin/python scripts/migration_gate.py run-live --case LIVE-005 --config-env PAPER_RAG_CONFIG",
  "report": "data/index/migration-gates/live/LIVE-005.json",
  "max_age_hours": 24,
  "requires_authorization": true,
  "side_effects": [
    "real LLM calls",
    "external paper search",
    "isolated paper download",
    "isolated SQLite writes",
    "isolated Qdrant writes",
    "isolated artifact writes",
    "versioned durable DSH session"
  ]
}
```

- [ ] **Step 6: Run deterministic headless tests**

Run:

```bash
pnpm --dir integrations/deepseek-harness exec vitest run tests/paper-rag-headless-runner.spec.mjs
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_migration_gate.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add integrations/deepseek-harness/src/paper-rag-headless-runner.mjs integrations/deepseek-harness/tests/paper-rag-headless-runner.spec.mjs scripts/migration_gate.py specs/20260813-deepseek-harness-migration/test/test-manifest.json tests/test_migration_gate.py
git commit -m "test: add dsh frontend workflow smoke"
```

If `tests/test_migration_gate.py` did not change, omit it from `git add`.

## Task 6: Full Integration Validation And Gate Reports

**Files:**
- Modify only when validation proves a bug in a source file from earlier tasks.
- Reports under `data/index/migration-gates/` are generated evidence and must not be committed.

**Interfaces:**
- Consumes all implementation tasks.
- Produces final verification commands, reports, and go/no-go evidence.

- [ ] **Step 1: Run DSH focused validation**

Run:

```bash
pnpm --dir integrations/deepseek-harness typecheck
pnpm --dir integrations/deepseek-harness test
pnpm --dir integrations/deepseek-harness smoke
pnpm --dir integrations/deepseek-harness dsh:dump-config
```

Expected: all commands exit 0. The dump-config audit must keep loopback host, disabled telemetry, `paper-research` default, and `deepseek-v4-flash`.

- [ ] **Step 2: Run Python MCP and migration focused validation**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_mcp_contract.py tests/test_mcp_tools.py tests/test_mcp_security.py tests/test_mcp_artifacts.py tests/test_mcp_operations.py tests/test_dsh_parity.py tests/test_mcp_frontend_contract.py tests/test_migration_gate.py
```

Expected: PASS.

- [ ] **Step 3: Run isolated DSH frontend live smoke only when credentials are available**

Run:

```bash
.venv/bin/python scripts/migration_gate.py run-live --case LIVE-005 --config-env PAPER_RAG_CONFIG
.venv/bin/python scripts/migration_gate.py validate-live --gate G2
```

Expected: `LIVE-005` report exists at `data/index/migration-gates/live/LIVE-005.json`, status `PASS`, authorized `true`, and all paths point to isolated live-workspace roots. If no API key is configured, record the exact missing credential as a blocker and continue with non-live validation.

- [ ] **Step 4: Run migration validators and secret scan**

Run:

```bash
.venv/bin/python scripts/migration_gate.py validate-cutover --spec specs/20260813-deepseek-harness-migration
.venv/bin/python scripts/secret_scan.py
rg -n "integrations/deer-flow|scripts/deerflow_smoke.py|deepseek-v4-pro|CHAT_MODEL=.*pro|SMALL_MODEL=.*pro|model:.*pro" integrations/deepseek-harness src tests scripts Makefile pyproject.toml
```

Expected: cutover validator PASS; secret scan exits 0; search shows no restored DeerFlow runtime path and no model switch to pro. Historical docs may still contain DeerFlow references classified by the cutover validator.

- [ ] **Step 5: Run final git hygiene**

Run:

```bash
git status --short --branch
git log --oneline -8
```

Expected: branch is clean after the final implementation commit; generated `data/index` reports are ignored.

- [ ] **Step 6: Commit final fixes if validation required source changes**

If validation required source edits, commit them:

```bash
git add <changed source and test files>
git commit -m "fix: stabilize dsh paper rag frontend validation"
```

Do not add generated reports, credentials, `.env`, real PDFs, isolated live workspaces, or runtime session files.

## Completion Audit

Before marking the goal complete, verify each item:

- Implementation plan exists at `docs/superpowers/plans/2026-08-14-dsh-web-paper-rag-frontend.md` and has a commit.
- DSH model catalog includes readonly, discovery, and approval-gated write tools needed for the core flow.
- Broker write tools require direct user boundary and approval, with side-effect reason text.
- Portable cards cover Corpus Status, Discovery Candidates, Ingest Receipt, Evidence Answer, and Artifact Delivery.
- MCP contract tests prove the card fields come from structuredContent.
- `Paper Research` preset guides the full workflow and keeps candidates out of answer evidence.
- Headless DSH frontend smoke report proves the DSH path, not only direct Python MCP.
- `deepseek-v4-flash` remains the model.
- No DeerFlow runtime path is restored.
- Secret scan passes.
- Required validation commands pass or a strict blocker is recorded.
- Git working tree is clean after implementation commits.
