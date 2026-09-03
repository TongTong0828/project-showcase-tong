import { appendFile } from "node:fs/promises";

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const statusInputSchema = {
  type: "object",
  properties: {},
  additionalProperties: false,
};

const listInputSchema = {
  type: "object",
  properties: {
    limit: { type: "number" },
  },
  additionalProperties: false,
};

const searchInputSchema = {
  type: "object",
  properties: {
    query: { type: "string" },
    top_k: { type: "number" },
    year_min: { type: "number" },
    year_max: { type: "number" },
  },
  required: ["query"],
  additionalProperties: false,
};

const qaInputSchema = {
  type: "object",
  properties: {
    question: { type: "string" },
    paper_ids: { type: "array", items: { type: "string" } },
    resolved_question: { type: "string" },
    top_k: { type: "number" },
  },
  required: ["question"],
  additionalProperties: false,
};

const sectionInputSchema = {
  type: "object",
  properties: {
    paper_id: { type: "string" },
    section_name: { type: "string" },
  },
  required: ["paper_id", "section_name"],
  additionalProperties: false,
};

const compareInputSchema = {
  type: "object",
  properties: {
    paper_ids: { type: "array", items: { type: "string" } },
    dimensions: { type: "array", items: { type: "string" } },
  },
  required: ["paper_ids", "dimensions"],
  additionalProperties: false,
};

const wikiInputSchema = {
  type: "object",
  properties: {
    concept: { type: "string" },
  },
  required: ["concept"],
  additionalProperties: false,
};

const writeInputSchema = {
  type: "object",
  properties: {
    note: { type: "string" },
  },
  required: ["note"],
  additionalProperties: false,
};

const discoverInputSchema = {
  type: "object",
  properties: {
    topic: { type: "string" },
    max_candidates: { type: "number" },
    sources: { type: "array", items: { type: "string" } },
  },
  required: ["topic"],
  additionalProperties: false,
};

const discoveryRunInputSchema = {
  type: "object",
  properties: {
    run_id: { type: "number" },
  },
  required: ["run_id"],
  additionalProperties: false,
};

const ingestInputSchema = {
  type: "object",
  properties: {
    arxiv_id: { type: "string" },
    pdf_url: { type: "string" },
    pdf_path: { type: "string" },
    title_hint: { type: "string" },
    force: { type: "boolean" },
  },
  additionalProperties: false,
};

const candidateIngestInputSchema = {
  type: "object",
  properties: {
    candidate_ids: { type: "array", items: { type: "number" } },
    force: { type: "boolean" },
  },
  required: ["candidate_ids"],
  additionalProperties: false,
};

const deliverInputSchema = {
  type: "object",
  properties: {
    format: { type: "string" },
    paper_ids: { type: "array", items: { type: "string" } },
    title: { type: "string" },
    options: { type: "object" },
  },
  required: ["format", "paper_ids"],
  additionalProperties: false,
};

const structuredOutputSchema = {
  type: "object",
  additionalProperties: true,
};

let writeCallCount = 0;

async function auditToolCall(toolName, args, receivedMeta, extra = {}) {
  if (process.env.PAPER_RAG_PRIVATE_AUDIT_PATH === undefined) {
    return;
  }

  await appendFile(
    process.env.PAPER_RAG_PRIVATE_AUDIT_PATH,
    `${JSON.stringify({
      tool_name: toolName,
      received_arguments: args,
      received_meta: receivedMeta,
      ...extra,
    })}\n`,
    "utf8",
  );
}

function abortReason(signal) {
  if (signal?.reason instanceof Error) {
    return signal.reason;
  }
  return new Error(String(signal?.reason ?? "cancelled"));
}

function delayOrAbort(signal, ms) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortReason(signal));
      return;
    }

    const timeout = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timeout);
        reject(abortReason(signal));
      },
      { once: true },
    );
  });
}

function credentialGeneration() {
  if (process.env.PAPER_RAG_TEST_TOKEN === "rotated-test-token") {
    return "rotated";
  }
  if (process.env.PAPER_RAG_TEST_TOKEN !== undefined) {
    return "initial";
  }
  return "absent";
}

const server = new Server(
  {
    name: "paper-rag-private-fixture",
    version: "0.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "paper_status",
      description: "Private fixture status tool.",
      inputSchema: statusInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "paper_list",
      description: "Private fixture paper list tool.",
      inputSchema: listInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "paper_search",
      description: "Private fixture paper search tool.",
      inputSchema: searchInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "paper_qa",
      description: "Private fixture paper qa tool.",
      inputSchema: qaInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "paper_section",
      description: "Private fixture paper section tool.",
      inputSchema: sectionInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "paper_compare",
      description: "Private fixture paper compare tool.",
      inputSchema: compareInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "wiki_lookup",
      description: "Private fixture wiki lookup tool.",
      inputSchema: wikiInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "paper_discover",
      description: "Private fixture paper discovery tool.",
      inputSchema: discoverInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "discovery_run_get",
      description: "Private fixture discovery run fetch tool.",
      inputSchema: discoveryRunInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "paper_ingest",
      description: "Private fixture paper ingest tool.",
      inputSchema: ingestInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "discovery_candidate_ingest",
      description: "Private fixture candidate ingest tool.",
      inputSchema: candidateIngestInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "paper_deliver",
      description: "Private fixture paper deliver tool.",
      inputSchema: deliverInputSchema,
      outputSchema: structuredOutputSchema,
    },
    {
      name: "write_probe",
      description: "Private fixture write probe.",
      inputSchema: writeInputSchema,
      outputSchema: structuredOutputSchema,
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
  const args = request.params.arguments ?? {};
  const receivedMeta = request.params._meta ?? {};
  await auditToolCall(request.params.name, args, receivedMeta);

  if (request.params.name === "paper_status" || request.params.name === "paper_search") {
    if (args.question === "slow-cancel" || args.query === "slow-cancel") {
      try {
        await delayOrAbort(extra.signal, 1000);
      } catch (error) {
        await auditToolCall(request.params.name, args, receivedMeta, {
          lifecycle: "cancelled",
        });
        throw error;
      }
    }

    const structuredContent = {
      ok: true,
      received_arguments: args,
      received_meta: receivedMeta,
      has_test_credential: Boolean(process.env.PAPER_RAG_TEST_TOKEN),
      credential_generation: credentialGeneration(),
      write_call_count: writeCallCount,
    };
    return {
      content: [{ type: "text", text: JSON.stringify({ ok: true }) }],
      structuredContent,
    };
  }

  if (
    [
      "paper_list",
      "paper_qa",
      "paper_section",
      "paper_compare",
      "wiki_lookup",
    ].includes(request.params.name)
  ) {
    const structuredContent = {
      ok: true,
      tool: request.params.name,
      received_arguments: args,
      received_meta: receivedMeta,
      has_test_credential: Boolean(process.env.PAPER_RAG_TEST_TOKEN),
      credential_generation: credentialGeneration(),
      write_call_count: writeCallCount,
      citations: request.params.name === "paper_qa" ? ["chunk:c1"] : [],
    };
    return {
      content: [{ type: "text", text: JSON.stringify({ ok: true }) }],
      structuredContent,
    };
  }

  if (request.params.name === "paper_discover" || request.params.name === "discovery_run_get") {
    const structuredContent = {
      ok: true,
      tool: request.params.name,
      received_arguments: args,
      received_meta: receivedMeta,
      data: {
        run: { id: args.run_id ?? 7, topic: args.topic ?? "fixture topic" },
        candidates: [
          {
            id: 11,
            title: "Fixture Candidate",
            source: "fixture",
            rank: 1,
            evidence_role: "discovery_only_not_answer_evidence",
          },
        ],
        count: 1,
      },
      evidence_role: "discovery_only",
      warnings: [],
    };
    return {
      content: [{ type: "text", text: JSON.stringify({ ok: true }) }],
      structuredContent,
    };
  }

  if (
    ["paper_ingest", "discovery_candidate_ingest", "paper_deliver"].includes(
      request.params.name,
    )
  ) {
    writeCallCount += 1;
    const data =
      request.params.name === "paper_deliver"
        ? {
            artifact: {
              artifact_id: "artifact-fixture",
              path: "/fixture/artifacts/artifact-fixture",
              manifest_path: "/fixture/artifacts/artifact-fixture/manifest.json",
            },
            format: args.format,
            paper_count: Array.isArray(args.paper_ids) ? args.paper_ids.length : 0,
          }
        : {
            results: [
              {
                candidate_id: Array.isArray(args.candidate_ids) ? args.candidate_ids[0] : undefined,
                paper_id: "paper-fixture",
                status: "ingested",
                n_chunks: 4,
              },
            ],
            count: 1,
          };
    const structuredContent = {
      ok: true,
      tool: request.params.name,
      received_arguments: args,
      received_meta: receivedMeta,
      data,
      evidence_role: request.params.name === "paper_deliver" ? "artifact" : "metadata",
      warnings: [],
      write_call_count: writeCallCount,
    };
    return {
      content: [{ type: "text", text: JSON.stringify({ ok: true }) }],
      structuredContent,
    };
  }

  if (request.params.name === "write_probe") {
    writeCallCount += 1;
    const structuredContent = {
      approved: true,
      received_arguments: args,
      received_meta: receivedMeta,
    };
    return {
      content: [{ type: "text", text: JSON.stringify({ approved: true }) }],
      structuredContent,
    };
  }

  throw new Error(`unknown fixture tool: ${request.params.name}`);
});

await server.connect(new StdioServerTransport());
