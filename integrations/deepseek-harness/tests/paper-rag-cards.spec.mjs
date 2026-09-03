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

    const card = createPortableCard(
      "paper_discover",
      { topic: "agentic rag" },
      structuredContent,
    );
    const markdown = renderPortableCardMarkdown(card);

    expect(card.type).toBe("discovery_candidates");
    expect(card.title).toBe("Discovery Candidates");
    expect(card.items[0]).toMatchObject({
      id: 11,
      title: "Agentic RAG",
      source: "arxiv",
    });
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
        chunks: [
          {
            chunk_id: "c1",
            paper_id: "paper-1",
            title: "Agentic RAG",
            text: "iterative retrieval",
          },
        ],
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

    const card = createPortableCard(
      "paper_deliver",
      { format: "pdf", paper_ids: ["p1"] },
      structuredContent,
    );
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
        data: {
          sqlite: { paper_count: 2, chunk_count: 9 },
          llm: { chat_model: "deepseek-v4-flash" },
        },
        warnings: [],
      },
    };

    const content = renderPaperRagResultForModel({}, value);
    const view = presentPaperRagResult({}, { content, isError: false, meta: value.structuredContent });
    const modelText = textContent(content[0]);

    expect(modelText).toContain("Corpus Status");
    expect(modelText).toContain("deepseek-v4-flash");
    expect(view).toMatchObject({ card: "generic", title: "Corpus Status" });
  });
});

function textContent(block) {
  if (block?.type !== "text") {
    throw new Error(`expected text content block, got ${block?.type}`);
  }
  return block.text;
}
