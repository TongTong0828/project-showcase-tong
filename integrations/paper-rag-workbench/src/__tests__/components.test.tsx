import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { ApprovalDialog } from "../components/ApprovalDialog";
import { AgentTimeline } from "../components/AgentTimeline";
import { AnswerPanel } from "../components/AnswerPanel";
import { CandidateTable } from "../components/CandidateTable";
import { ChunkDetailPanel } from "../components/ChunkDetailPanel";
import { CitationChips } from "../components/CitationChips";
import { CompareMatrix } from "../components/CompareMatrix";
import { DshHandoffDialog } from "../components/DshHandoffDialog";
import { EvidenceChunkCard } from "../components/EvidenceChunkCard";
import { HealthSummary } from "../components/HealthSummary";
import { PaperDetailPanel } from "../components/PaperDetailPanel";
import { PaperTable } from "../components/PaperTable";
import { QualityIssueTable } from "../components/QualityIssueTable";
import { ScoreBreakdown } from "../components/ScoreBreakdown";
import { Shell } from "../components/Shell";
import { createWorkbenchClient } from "../api/client";
import { ProjectProvider, useProjectContext } from "../context/ProjectContext";
import { renderWithI18n } from "../test/render";
import {
  chunkDetailFixture,
  dshHandoffFixture,
  indexHealthFixture,
  paperDetailFixture,
  qaStreamFixture,
} from "../api/fixtures";
import type { CompareRun, PaperSummary } from "../types";

beforeEach(() => {
  window.localStorage.clear();
});

describe("Shell", () => {
  test("renders Chinese navigation by default", () => {
    renderWithI18n(
      <Shell active="overview" onNavigate={vi.fn()}>
        <p>body</p>
      </Shell>,
    );

    expect(screen.getByRole("navigation", { name: "工作台导航" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "概览" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "健康检查" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "DSH 对话" })).toBeInTheDocument();
  });

  test("language toggle switches navigation to English", async () => {
    const user = userEvent.setup();

    renderWithI18n(
      <Shell active="overview" onNavigate={vi.fn()}>
        <p>body</p>
      </Shell>,
    );

    await user.click(screen.getByRole("button", { name: "EN" }));

    expect(screen.getByRole("navigation", { name: "Workbench navigation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: "中" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "EN" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("PaperTable", () => {
  test("renders indexed papers and dispatches row actions with the selected paper", async () => {
    const user = userEvent.setup();
    const paper: PaperSummary = {
      paper_id: "arxiv:2310.11511",
      title: "Self-RAG",
      arxiv_id: "2310.11511",
      chunk_count: 58,
    };
    const onAsk = vi.fn();
    const onSearch = vi.fn();
    const onSection = vi.fn();

    renderWithI18n(
      <PaperTable
        papers={[paper]}
        onAsk={onAsk}
        onSearch={onSearch}
        onSection={onSection}
      />,
    );

    expect(screen.getByText("Self-RAG")).toBeInTheDocument();
    expect(screen.getByText("arxiv:2310.11511")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /提问 self-rag/i }));
    await user.click(screen.getByRole("button", { name: /检索 self-rag/i }));
    await user.click(screen.getByRole("button", { name: /打开章节 self-rag/i }));

    expect(onAsk).toHaveBeenCalledWith(paper);
    expect(onSearch).toHaveBeenCalledWith(paper);
    expect(onSection).toHaveBeenCalledWith(paper);
  });
});

describe("Evidence components", () => {
  test("EvidenceChunkCard shows safe chunk metadata", () => {
    renderWithI18n(
      <EvidenceChunkCard
        chunk={{
          chunk_id: "c1",
          paper_id: "p1",
          title: "Paper",
          page: 3,
          text: "bounded evidence text",
        }}
      />,
    );

    expect(screen.getByText("Paper")).toBeInTheDocument();
    expect(screen.getByText("p1")).toBeInTheDocument();
    expect(screen.getByText("第 3 页")).toBeInTheDocument();
    expect(screen.getByText("chunk:c1")).toBeInTheDocument();
  });

  test("CitationChips dispatches selected citation ids", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();

    renderWithI18n(<CitationChips citations={["c1", "c2"]} onSelect={onSelect} />);

    await user.click(screen.getByRole("button", { name: "c2" }));

    expect(onSelect).toHaveBeenCalledWith("c2");
  });

  test("AnswerPanel shows citation chips and evidence", () => {
    renderWithI18n(
      <AnswerPanel
        answer="Self-RAG critiques generations."
        citations={["c1"]}
        chunks={[{ chunk_id: "c1", paper_id: "p1", text: "reflection tokens" }]}
        abstain={{ decision: "answer" }}
      />,
    );

    expect(screen.getByText(/critiques generations/i)).toBeInTheDocument();
    expect(screen.getByText("c1")).toBeInTheDocument();
    expect(screen.getByText(/reflection tokens/i)).toBeInTheDocument();
  });

  test("AnswerPanel renders user note references separately from paper citations", () => {
    renderWithI18n(
      <AnswerPanel
        answer="Self-RAG critiques generations."
        citations={["chunk-self-rag-1"]}
        noteRefs={["note-self-rag-1"]}
        chunks={[]}
        abstain={{ decision: "answer" }}
      />,
    );

    expect(screen.getByText("chunk-self-rag-1")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /用户笔记引用/ })).toBeInTheDocument();
    expect(screen.getByText("note-self-rag-1")).toBeInTheDocument();
  });
});

describe("Discovery approval components", () => {
  test("CandidateTable labels candidates as non-evidence", () => {
    renderWithI18n(
      <CandidateTable
        candidates={[
          {
            id: 11,
            title: "Candidate Paper",
            source: "arxiv",
            rank: 1,
            evidence_role: "discovery_only_not_answer_evidence",
          },
        ]}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText("Candidate Paper")).toBeInTheDocument();
    expect(screen.getByText(/不是回答证据/)).toBeInTheDocument();
  });

  test("ApprovalDialog names side effects before approval", () => {
    renderWithI18n(
      <ApprovalDialog
        open
        candidateIds={[11]}
        onCancel={vi.fn()}
        onApprove={vi.fn()}
      />,
    );

    expect(screen.getByText(/候选 ID：11/)).toBeInTheDocument();
    expect(screen.getByText(/写入索引论文和分块/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /批准入库/ })).toBeInTheDocument();
  });
});

describe("Health diagnostics components", () => {
  test("health summary distinguishes degraded services", () => {
    renderWithI18n(<HealthSummary data={indexHealthFixture} />);

    expect(screen.getByRole("heading", { name: /索引健康/ })).toBeInTheDocument();
    expect(screen.getAllByText(/降级/).length).toBeGreaterThan(0);
    expect(screen.getByText(/sparse fallback/i)).toBeInTheDocument();
    expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
  });

  test("quality issue table shows duplicate and parser samples", () => {
    renderWithI18n(<QualityIssueTable samples={indexHealthFixture.corpus_quality.samples} />);

    expect(screen.getByText(/duplicate_chunk/i)).toBeInTheDocument();
    expect(screen.getByText(/parser_artifact/i)).toBeInTheDocument();
    expect(screen.getByText(/05e56a78/)).toBeInTheDocument();
  });
});

describe("Paper and chunk drilldown components", () => {
  test("paper detail panel lists sections and chunks", () => {
    renderWithI18n(<PaperDetailPanel detail={paperDetailFixture} onInspectChunk={() => {}} />);

    expect(screen.getByRole("heading", { name: /Self-RAG/i })).toBeInTheDocument();
    expect(screen.getByText("Abstract")).toBeInTheDocument();
    expect(screen.getByText("Introduction")).toBeInTheDocument();
    expect(screen.getByText(/parser_artifacts_detected/i)).toBeInTheDocument();
  });

  test("paper detail panel exposes project actions for paper notes and chunk pins", async () => {
    const user = userEvent.setup();
    const client = createWorkbenchClient({ fixtureMode: true });

    renderWithI18n(
      <ProjectProvider client={client}>
        <PaperDetailPanel detail={paperDetailFixture} onInspectChunk={() => {}} />
      </ProjectProvider>,
    );

    expect(await screen.findByRole("button", { name: /已在项目中/ })).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /钉选证据 chunk-self-rag-2/i }),
    );
    await user.type(screen.getAllByLabelText(/^笔记$/)[0], "paper-level note");
    await user.click(screen.getAllByRole("button", { name: /保存笔记/ })[0]);

    const detail = await client.project("project-self-rag");
    expect(detail.evidence.some((pin) => pin.chunk_id === "chunk-self-rag-2")).toBe(true);
    expect(
      detail.notes.some(
        (note) =>
          note.target_type === "paper" &&
          note.target_id === "arxiv:2310.11511" &&
          note.body === "paper-level note",
      ),
    ).toBe(true);
  });

  test("chunk detail panel shows full text and neighbors", () => {
    renderWithI18n(<ChunkDetailPanel detail={chunkDetailFixture} onOpenPaper={() => {}} />);

    expect(screen.getByText(/critiques its own generations/i)).toBeInTheDocument();
    expect(screen.getByText(/html_comment/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /打开论文详情/ })).toBeInTheDocument();
  });

  test("score breakdown renders known score fields", () => {
    renderWithI18n(
      <ScoreBreakdown
        chunk={{
          ...chunkDetailFixture.chunk,
          score: 0.92,
          dense_score: 0.81,
          sparse_score: 0.74,
        }}
      />,
    );

    expect(screen.getByText(/score 0.92/i)).toBeInTheDocument();
    expect(screen.getByText(/dense 0.81/i)).toBeInTheDocument();
    expect(screen.getByText(/sparse 0.74/i)).toBeInTheDocument();
  });
});

describe("DSH handoff components", () => {
  test("dsh handoff dialog shows prompt and open link", () => {
    renderWithI18n(<DshHandoffDialog data={dshHandoffFixture} onClose={() => {}} />);

    expect(screen.getByRole("dialog", { name: /发送到 DSH/ })).toBeInTheDocument();
    expect(screen.getByText(/基于 Paper RAG Workbench/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /打开 DSH/ })).toHaveAttribute(
      "href",
      "http://127.0.0.1:3080",
    );
  });
});

describe("Streaming timeline components", () => {
  test("agent timeline renders stage progress", () => {
    renderWithI18n(<AgentTimeline stages={qaStreamFixture.stages} running={false} />);

    expect(screen.getByRole("heading", { name: /执行轨迹/ })).toBeInTheDocument();
    expect(screen.getByText(/Understanding question/i)).toBeInTheDocument();
    expect(screen.getByText(/Retrieved 2 chunks/i)).toBeInTheDocument();
  });
});

describe("Project context", () => {
  test("loads fixture projects and creates an active project", async () => {
    const user = userEvent.setup();
    const client = createWorkbenchClient({ fixtureMode: true });

    function Probe() {
      const { activeProject, createProject, projects } = useProjectContext();
      return (
        <div>
          <p>projects:{projects.length}</p>
          <p>active:{activeProject?.project.name ?? "none"}</p>
          <button
            type="button"
            onClick={() => createProject("Scoped Notes 调研", "notes")}
          >
            create
          </button>
        </div>
      );
    }

    renderWithI18n(
      <ProjectProvider client={client}>
        <Probe />
      </ProjectProvider>,
    );

    expect(await screen.findByText("active:Self-RAG 调研")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "create" }));

    expect(await screen.findByText("active:Scoped Notes 调研")).toBeInTheDocument();
  });
});

describe("Compare components", () => {
  test("compare matrix shows evidence chunk ids and missing evidence states", () => {
    const run: CompareRun = {
      run_id: "compare-1",
      project_id: "project-self-rag",
      dimensions: ["method", "limitation"],
      paper_ids: ["arxiv:2310.11511", "arxiv:2005.11401"],
      status: "degraded",
      warnings: ["LLM synthesis unavailable; rendered evidence-only matrix."],
      cells: [
        {
          paper_id: "arxiv:2310.11511",
          dimension: "method",
          summary: "Evidence pinned for method: SELF-RAG retrieves passages on demand.",
          evidence_chunk_ids: ["chunk-self-rag-1"],
          note_ids: ["note-self-rag-1"],
          confidence: "evidence_backed",
        },
        {
          paper_id: "arxiv:2005.11401",
          dimension: "method",
          summary: "No pinned evidence",
          evidence_chunk_ids: [],
          note_ids: [],
          confidence: "missing",
        },
      ],
      created_at: "2026-08-15T00:00:00Z",
    };

    renderWithI18n(<CompareMatrix run={run} />);

    expect(screen.getByText("chunk-self-rag-1")).toBeInTheDocument();
    expect(screen.getAllByText("No pinned evidence").length).toBeGreaterThan(0);
    expect(screen.getByText(/evidence_backed/)).toBeInTheDocument();
  });
});
