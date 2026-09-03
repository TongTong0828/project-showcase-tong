import { screen, waitForElementToBeRemoved } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { describe, expect, test, vi } from "vitest";

import { createWorkbenchClient } from "../api/client";
import { AskPage } from "../pages/AskPage";
import { DiscoverPage } from "../pages/DiscoverPage";
import { ComparePage } from "../pages/ComparePage";
import { HealthPage } from "../pages/HealthPage";
import { LibraryPage } from "../pages/LibraryPage";
import { OverviewPage } from "../pages/OverviewPage";
import { SearchPage } from "../pages/SearchPage";
import { WorkspacePage } from "../pages/WorkspacePage";
import { ProjectProvider, useProjectContext } from "../context/ProjectContext";
import { renderWithI18n } from "../test/render";

describe("Overview and Library pages", () => {
  test("overview shows corpus health, model status, and DSH bridge", async () => {
    window.localStorage.clear();
    renderWithI18n(<OverviewPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await waitForElementToBeRemoved(() => screen.queryByText(/正在加载概览/));

    expect(screen.getByRole("heading", { name: "概览" })).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("345")).toBeInTheDocument();
    expect(screen.getAllByText("deepseek-v4-flash").length).toBeGreaterThan(0);
    expect(screen.getByText("已配置")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /打开 DSH 对话/ })).toHaveAttribute(
      "href",
      "http://127.0.0.1:3080",
    );
  });

  test("library filters papers and opens a readable section drawer", async () => {
    const user = userEvent.setup();
    window.localStorage.clear();

    renderWithI18n(<LibraryPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await waitForElementToBeRemoved(() => screen.queryByText(/正在加载论文库/));
    expect(screen.getByText(/Self-RAG/)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/筛选论文/), "2005");

    expect(screen.getByText(/Retrieval-Augmented Generation/)).toBeInTheDocument();
    expect(screen.queryByText(/Self-RAG/)).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText(/筛选论文/));
    await user.click(screen.getByRole("button", { name: /打开章节 self-rag/i }));

    expect(await screen.findByRole("heading", { name: /引言/ })).toBeInTheDocument();
    expect(screen.getByText(/retrieves passages on demand/i)).toBeInTheDocument();
  });

  test("search page renders evidence chunks", async () => {
    const user = userEvent.setup();
    window.localStorage.clear();
    renderWithI18n(<SearchPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await user.type(screen.getByLabelText(/检索证据/), "reflection tokens");
    await user.click(screen.getByRole("button", { name: /^检索$/ }));

    expect(await screen.findByText("chunk:chunk-self-rag-1")).toBeInTheDocument();
    expect(screen.getByText(/retrieves passages on demand/i)).toBeInTheDocument();
  });

  test("ask page renders answer citations and DSH prompt bridge", async () => {
    const user = userEvent.setup();
    window.localStorage.clear();
    renderWithI18n(<AskPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await user.type(screen.getByLabelText(/问题/), "What is Self-RAG?");
    await user.click(screen.getByRole("button", { name: /^提问$/ }));

    expect(await screen.findByText(/decide when to retrieve/i)).toBeInTheDocument();
    expect(screen.getByText("chunk-self-rag-1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /复制 DSH 提示词/ })).toBeInTheDocument();
  });

  test("discover requires approval before candidate ingest", async () => {
    const user = userEvent.setup();
    window.localStorage.clear();
    const baseClient = createWorkbenchClient({ fixtureMode: true });
    const ingestCandidates = vi.fn(baseClient.ingestCandidates);
    const client = { ...baseClient, ingestCandidates };

    renderWithI18n(<DiscoverPage client={client} />);

    await user.type(screen.getByLabelText(/主题/), "agentic rag");
    await user.click(screen.getByRole("button", { name: /^发现$/ }));
    expect(await screen.findByText(/Agentic Retrieval/)).toBeInTheDocument();

    await user.click(screen.getByLabelText(/选择候选 11/));
    await user.click(screen.getByRole("button", { name: /入库所选/ }));
    expect(ingestCandidates).not.toHaveBeenCalled();
    expect(screen.getByText(/写入索引论文和分块/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /批准入库/ }));
    expect(await screen.findByText(/arxiv:2601.00001/)).toBeInTheDocument();
    expect(ingestCandidates).toHaveBeenCalledWith(
      expect.objectContaining({
        candidate_ids: [11],
        approval: expect.objectContaining({
          approved: true,
          operation: "discovery_candidate_ingest",
          candidate_ids: [11],
          destination: "real-library",
        }),
      }),
    );
  });

  test("health page loads index diagnostics", async () => {
    window.localStorage.clear();
    renderWithI18n(<HealthPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await waitForElementToBeRemoved(() => screen.queryByText(/正在加载健康检查/));

    expect(screen.getByRole("heading", { name: "健康检查" })).toBeInTheDocument();
    expect(screen.getByText(/Dense retrieval is unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/345/)).toBeInTheDocument();
  });

  test("library opens paper detail", async () => {
    const user = userEvent.setup();
    window.localStorage.clear();
    renderWithI18n(<LibraryPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await waitForElementToBeRemoved(() => screen.queryByText(/正在加载论文库/));
    await user.click(screen.getByRole("button", { name: /查看论文 self-rag/i }));

    expect(await screen.findByRole("heading", { name: /Self-RAG/i })).toBeInTheDocument();
    expect(screen.getByText(/Abstract/)).toBeInTheDocument();
  });

  test("ask citation opens chunk drilldown", async () => {
    const user = userEvent.setup();
    window.localStorage.clear();
    renderWithI18n(<AskPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await user.type(screen.getByLabelText(/问题/), "What is Self-RAG?");
    await user.click(screen.getByRole("button", { name: /^提问$/ }));
    await user.click(await screen.findByRole("button", { name: /chunk-self-rag-1/i }));

    expect(await screen.findByText(/critiques its own generations/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /打开论文详情/ })).toBeInTheDocument();
  });

  test("search evidence card opens chunk drilldown", async () => {
    const user = userEvent.setup();
    window.localStorage.clear();
    renderWithI18n(<SearchPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await user.type(screen.getByLabelText(/检索证据/), "reflection tokens");
    await user.click(screen.getByRole("button", { name: /^检索$/ }));
    await user.click(
      await screen.findByRole("button", { name: /查看分块 chunk-self-rag-1/i }),
    );

    expect(await screen.findByText(/critiques its own generations/i)).toBeInTheDocument();
  });

  test("ask page creates a structured dsh handoff", async () => {
    const user = userEvent.setup();
    window.localStorage.clear();
    const baseClient = createWorkbenchClient({ fixtureMode: true });
    const dshHandoff = vi.fn(baseClient.dshHandoff);
    const client = { ...baseClient, dshHandoff };

    renderWithI18n(<AskPage client={client} />);

    await user.type(screen.getByLabelText(/问题/), "What is Self-RAG?");
    await user.click(screen.getByRole("button", { name: /^提问$/ }));
    await user.click(await screen.findByRole("button", { name: /发送到 DSH/ }));

    expect(dshHandoff).toHaveBeenCalledWith(
      expect.objectContaining({
        question: "What is Self-RAG?",
        paper_ids: expect.arrayContaining(["arxiv:2310.11511"]),
        chunk_ids: expect.arrayContaining(["chunk-self-rag-1"]),
        source: "ask",
      }),
    );
    expect(await screen.findByRole("dialog", { name: /发送到 DSH/ })).toBeInTheDocument();
  });

  test("ask page streams answer and shows agent timeline", async () => {
    const user = userEvent.setup();
    window.localStorage.clear();
    renderWithI18n(<AskPage client={createWorkbenchClient({ fixtureMode: true })} />);

    await user.type(screen.getByLabelText(/问题/), "What is Self-RAG?");
    await user.click(screen.getByRole("button", { name: /^提问$/ }));

    expect(await screen.findByRole("heading", { name: /执行轨迹/ })).toBeInTheDocument();
    expect(await screen.findByText(/Understanding question/i)).toBeInTheDocument();
    expect(await screen.findByText(/decide when to retrieve/i)).toBeInTheDocument();
    expect(screen.getByText("chunk-self-rag-1")).toBeInTheDocument();
  });

  test("ask page keeps global QA payload unchanged when context toggles are off", async () => {
    const user = userEvent.setup();
    const baseClient = createWorkbenchClient({ fixtureMode: true });
    const qaStream = vi.fn(async (...args: Parameters<typeof baseClient.qaStream>) => {
      const [, onEvent] = args;
      onEvent({
        event: "done",
        data: {
          trace_id: "trace-global",
          stage: "done",
          status: "completed",
          answer: "Global answer",
          citations: [],
          chunks: [],
          abstain: { decision: "answer" },
        },
      });
    });
    const client = { ...baseClient, qaStream };

    renderWithI18n(
      <ProjectProvider client={client}>
        <AskPage client={client} />
      </ProjectProvider>,
    );

    await user.type(screen.getByLabelText(/问题/), "What is Self-RAG?");
    await user.click(screen.getByRole("button", { name: /^提问$/ }));

    expect(await screen.findByText(/Global answer/)).toBeInTheDocument();
    expect(qaStream.mock.calls[0][0]).not.toHaveProperty("project_id");
    expect(qaStream.mock.calls[0][0]).not.toHaveProperty("context_policy");
  });

  test("ask page sends scoped context and saves the scoped policy", async () => {
    const user = userEvent.setup();
    const baseClient = createWorkbenchClient({ fixtureMode: true });
    const qaStream = vi.fn(async (...args: Parameters<typeof baseClient.qaStream>) => {
      const [input, onEvent] = args;
      onEvent({
        event: "done",
        data: {
          trace_id: "trace-scoped",
          stage: "done",
          status: "completed",
          answer: "Scoped answer",
          citations: ["chunk-self-rag-1"],
          note_refs: ["note-self-rag-1"],
          context_policy: input.context_policy,
          chunks: [],
          abstain: { decision: "answer" },
        },
      });
    });
    const client = { ...baseClient, qaStream };

    renderWithI18n(
      <ProjectProvider client={client}>
        <AskPage client={client} />
      </ProjectProvider>,
    );

    await user.click(await screen.findByLabelText(/包含钉选证据/));
    await user.click(screen.getByLabelText(/包含笔记/));
    await user.click(screen.getByLabelText(/限制到项目论文/));
    await user.type(screen.getByLabelText(/问题/), "What is Self-RAG?");
    await user.click(screen.getByRole("button", { name: /^提问$/ }));

    expect(await screen.findByText(/Scoped answer/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /用户笔记引用/ })).toBeInTheDocument();
    expect(screen.getByText("note-self-rag-1")).toBeInTheDocument();
    expect(qaStream.mock.calls[0][0]).toMatchObject({
      project_id: "project-self-rag",
      context_policy: {
        include_pinned_evidence: true,
        include_notes: true,
        restrict_to_project_papers: true,
      },
    });

    await user.click(screen.getByRole("button", { name: /保存问答/ }));
    const detail = await client.project("project-self-rag");
    expect(detail.saved_questions[0].context_policy).toEqual({
      include_pinned_evidence: true,
      include_notes: true,
      restrict_to_project_papers: true,
    });
  });

  test("workspace page creates a project and generates project DSH handoff", async () => {
    const user = userEvent.setup();
    const client = createWorkbenchClient({ fixtureMode: true });

    renderWithI18n(
      <ProjectProvider client={client}>
        <WorkspacePage />
      </ProjectProvider>,
    );

    expect(await screen.findByRole("heading", { name: /工作区/ })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/项目名称/), "Scoped Notes 调研");
    await user.click(screen.getByRole("button", { name: /创建项目/ }));

    expect(await screen.findByText(/Scoped Notes 调研/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^笔记$/), "local project note");
    await user.click(screen.getByRole("button", { name: /保存笔记/ }));
    expect(await screen.findByText(/local project note/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/DSH 任务/), "Compare methods.");
    await user.click(screen.getByRole("button", { name: /发送项目到 DSH/ }));

    expect(await screen.findByRole("dialog", { name: /发送到 DSH/ })).toBeInTheDocument();
    expect(screen.getByText(/Compare methods/)).toBeInTheDocument();
  });

  test("library can add a paper to the active project", async () => {
    const user = userEvent.setup();
    const client = createWorkbenchClient({ fixtureMode: true });

    renderWithI18n(
      <ProjectProvider client={client}>
        <LibraryPage client={client} />
      </ProjectProvider>,
    );

    await waitForElementToBeRemoved(() => screen.queryByText(/正在加载论文库/));
    await user.click(screen.getByRole("button", { name: /加入项目 self-rag/i }));

    const detail = await client.project("project-self-rag");
    expect(detail.papers.some((paper) => paper.paper_id === "arxiv:2310.11511")).toBe(true);
    expect(await screen.findByText(/已加入当前项目/)).toBeInTheDocument();
  });

  test("search can pin evidence to the active project", async () => {
    const user = userEvent.setup();
    const client = createWorkbenchClient({ fixtureMode: true });

    renderWithI18n(
      <ProjectProvider client={client}>
        <SearchPage client={client} />
      </ProjectProvider>,
    );

    await user.type(screen.getByLabelText(/检索证据/), "reflection tokens");
    await user.click(screen.getByRole("button", { name: /^检索$/ }));
    await user.click(await screen.findByRole("button", { name: /钉选证据 chunk-self-rag-1/i }));

    const detail = await client.project("project-self-rag");
    expect(detail.evidence.some((pin) => pin.chunk_id === "chunk-self-rag-1")).toBe(true);
    expect(await screen.findByText(/已钉选/)).toBeInTheDocument();
  });

  test("search can add a result paper to the active project", async () => {
    const user = userEvent.setup();
    const client = createWorkbenchClient({ fixtureMode: true });
    const created = await client.createProject({ name: "Search project" });

    function SelectProject() {
      const { projects, setActiveProjectId } = useProjectContext();
      useEffect(() => {
        if (projects.some((project) => project.project_id === created.project.project_id)) {
          setActiveProjectId(created.project.project_id);
        }
      }, [projects, setActiveProjectId]);
      return null;
    }

    renderWithI18n(
      <ProjectProvider client={client}>
        <SelectProject />
        <SearchPage client={client} />
      </ProjectProvider>,
    );

    await user.type(screen.getByLabelText(/检索证据/), "reflection tokens");
    await user.click(screen.getByRole("button", { name: /^检索$/ }));
    const addPaperButtons = await screen.findAllByRole("button", {
      name: /加入项目 self-rag/i,
    });
    await user.click(addPaperButtons[0]);

    const detail = await client.project(created.project.project_id);
    expect(detail.papers.some((paper) => paper.paper_id === "arxiv:2310.11511")).toBe(true);
  });

  test("ask can save answer to the active project", async () => {
    const user = userEvent.setup();
    const client = createWorkbenchClient({ fixtureMode: true });

    renderWithI18n(
      <ProjectProvider client={client}>
        <AskPage client={client} />
      </ProjectProvider>,
    );

    await user.type(screen.getByLabelText(/问题/), "What is Self-RAG?");
    await user.click(screen.getByRole("button", { name: /^提问$/ }));
    await user.click(await screen.findByRole("button", { name: /保存问答/ }));

    const detail = await client.project("project-self-rag");
    expect(detail.saved_questions.some((saved) => saved.question === "What is Self-RAG?")).toBe(
      true,
    );
    expect(detail.saved_questions[0].citation_papers).toMatchObject({
      "chunk-self-rag-1": "arxiv:2310.11511",
    });
    expect(await screen.findByText(/问答已保存/)).toBeInTheDocument();
  });

  test("compare page creates an evidence-first matrix and DSH handoff", async () => {
    const user = userEvent.setup();
    const client = createWorkbenchClient({ fixtureMode: true });

    renderWithI18n(
      <ProjectProvider client={client}>
        <ComparePage client={client} />
      </ProjectProvider>,
    );

    expect(await screen.findByRole("heading", { name: /对比/ })).toBeInTheDocument();
    await user.click(screen.getByLabelText(/方法/));
    await user.click(screen.getByLabelText(/限制/));
    await user.click(screen.getByRole("button", { name: /生成对比/ }));

    expect((await screen.findAllByText("chunk-self-rag-1")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/No pinned evidence/).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /发送对比到 DSH/ }));

    expect(await screen.findByRole("dialog", { name: /发送到 DSH/ })).toBeInTheDocument();
    expect(screen.getByText(/Compare run/)).toBeInTheDocument();
  });

  test("compare page sends only the selected paper subset", async () => {
    const user = userEvent.setup();
    const baseClient = createWorkbenchClient({ fixtureMode: true });
    const createCompareRun = vi.fn(baseClient.createCompareRun);
    const client = { ...baseClient, createCompareRun };

    renderWithI18n(
      <ProjectProvider client={client}>
        <ComparePage client={client} />
      </ProjectProvider>,
    );

    expect(await screen.findByRole("heading", { name: /对比/ })).toBeInTheDocument();
    await user.click(screen.getByLabelText(/Retrieval-Augmented Generation/));
    await user.click(screen.getByLabelText(/方法/));
    await user.click(screen.getByRole("button", { name: /生成对比/ }));

    expect(createCompareRun.mock.calls[0][1].paper_ids).toEqual(["arxiv:2310.11511"]);
  });
});
