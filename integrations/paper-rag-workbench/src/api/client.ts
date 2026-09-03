import {
  chunkDetailFixture,
  discoverFixture,
  dshHandoffFixture,
  indexHealthFixture,
  ingestFixture,
  paperDetailFixture,
  papersFixture,
  projectDetailFixture,
  projectFixture,
  qaFixture,
  qaStreamEventsFixture,
  searchFixture,
  sectionFixture,
  statusFixture,
} from "./fixtures";
import { streamPaperQa } from "./qaStream";
import type {
  CandidateIngestInput,
  ChunkDetailData,
  CompareInput,
  CompareRun,
  DiscoverData,
  DiscoverInput,
  DshHandoffData,
  DshHandoffInput,
  EvidencePinInput,
  HealthData,
  IndexHealthData,
  IngestData,
  McpEnvelope,
  NoteInput,
  PaperDetailData,
  PaperListData,
  ProjectCreateInput,
  ProjectDetail,
  ProjectHandoffInput,
  ProjectPaperInput,
  ProjectSummary,
  ProjectUpdateInput,
  QaData,
  QaInput,
  QaStreamHandler,
  SavedQuestionInput,
  SearchData,
  SearchInput,
  SectionData,
  SectionInput,
  StatusData,
  WorkbenchClient,
} from "../types";

type FetchLike = typeof fetch;

export function createWorkbenchClient(
  options: { baseUrl?: string; fixtureMode?: boolean; fetchImpl?: FetchLike } = {},
): WorkbenchClient {
  const baseUrl = options.baseUrl ?? "";
  const fetchImpl = options.fetchImpl ?? fetch;
  const fixtureMode = options.fixtureMode ?? import.meta.env.VITE_WORKBENCH_FIXTURES === "1";
  const fixtureDetails = new Map<string, ProjectDetail>([
    [projectFixture.project_id, clone(projectDetailFixture)],
  ]);

  const get = async <T>(path: string): Promise<T> => {
    const response = await fetchImpl(`${baseUrl}${path}`);
    if (!response.ok) throw new Error(`GET ${path} failed with ${response.status}`);
    return response.json() as Promise<T>;
  };
  const requestError = async (method: string, path: string, response: Response) => {
    let suffix = "";
    try {
      const payload = await response.json();
      const message =
        payload?.detail?.error?.message ??
        payload?.detail?.message ??
        payload?.message;
      if (message) suffix = `: ${message}`;
    } catch {
      // Error bodies may be empty or non-JSON.
    }
    return new Error(`${method} ${path} failed with ${response.status}${suffix}`);
  };
  const post = async <T>(path: string, body: unknown): Promise<T> => {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw await requestError("POST", path, response);
    return response.json() as Promise<T>;
  };
  const patch = async <T>(path: string, body: unknown): Promise<T> => {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw await requestError("PATCH", path, response);
    return response.json() as Promise<T>;
  };
  const fixtureProjectList = (): ProjectSummary[] =>
    Array.from(fixtureDetails.values()).map((detail) => clone(detail.project));
  const fixtureProject = (projectId: string): ProjectDetail => {
    const detail = fixtureDetails.get(projectId);
    if (!detail) throw new Error(`Fixture project not found: ${projectId}`);
    return detail;
  };
  const refreshSummary = (detail: ProjectDetail) => {
    detail.summary = {
      paper_count: detail.papers.length,
      evidence_count: detail.evidence.length,
      note_count: detail.notes.length,
      saved_question_count: detail.saved_questions.length,
      compare_run_count: detail.compare_runs.length,
    };
    detail.project.updated_at = nowFixture();
  };
  const buildFixtureCompareRun = (projectId: string, input: CompareInput): CompareRun => {
    const detail = fixtureProject(projectId);
    const paperIds =
      input.paper_ids.length > 0
        ? input.paper_ids
        : detail.papers.map((paper) => paper.paper_id);
    const dimensions = input.dimensions.length > 0 ? input.dimensions : ["method"];
    const cells: CompareRun["cells"] = paperIds.flatMap((paperId) => {
      const pins = detail.evidence.filter((pin) => pin.paper_id === paperId);
      const noteIds = detail.notes
        .filter(
          (note) =>
            (note.target_type === "paper" && note.target_id === paperId) ||
            (note.target_type === "chunk" &&
              pins.some((pin) => pin.chunk_id === note.target_id)),
        )
        .map((note) => note.note_id);
      return dimensions.map((dimension) => ({
        paper_id: paperId,
        dimension,
        summary: pins.length
          ? `Evidence pinned for ${dimension}: ${pins[0].quote_snapshot}`
          : "No pinned evidence",
        evidence_chunk_ids: pins.map((pin) => pin.chunk_id),
        note_ids: noteIds,
        confidence: pins.length ? "evidence_backed" : "missing",
      }));
    });
    return {
      run_id: `compare-${detail.compare_runs.length + 1}`,
      project_id: projectId,
      dimensions,
      paper_ids: paperIds,
      status: "degraded",
      cells,
      warnings: ["LLM synthesis unavailable; rendered evidence-only matrix."],
      created_at: nowFixture(),
    };
  };
  const fixtureQaEnvelope = (input: QaInput): McpEnvelope<QaData> => {
    const envelope = clone(qaFixture);
    if (!input.project_id || !input.context_policy || !envelope.data) return envelope;
    const detail = fixtureProject(input.project_id);
    envelope.data.note_refs = input.context_policy.include_notes
      ? detail.notes.map((note) => note.note_id)
      : [];
    envelope.data.context_policy = input.context_policy;
    envelope.data.project_context_warnings = [];
    return envelope;
  };

  return {
    health: (): Promise<HealthData> =>
      fixtureMode
        ? Promise.resolve({
            ok: true,
            service: "paper-rag-workbench",
            dsh_url: "http://127.0.0.1:3080",
            models: {
              chat_model: "deepseek-v4-flash",
              small_model: "deepseek-v4-flash",
            },
          })
        : get("/api/health"),
    indexHealth: (): Promise<IndexHealthData> =>
      fixtureMode ? Promise.resolve(indexHealthFixture) : get("/api/health/index"),
    status: (): Promise<McpEnvelope<StatusData>> =>
      fixtureMode ? Promise.resolve(statusFixture) : get("/api/status"),
    papers: (limit = 20): Promise<McpEnvelope<PaperListData>> =>
      fixtureMode
        ? Promise.resolve(papersFixture)
        : get(`/api/papers?limit=${encodeURIComponent(limit)}`),
    paperDetail: (paperId: string): Promise<PaperDetailData> =>
      fixtureMode
        ? Promise.resolve(paperDetailFixture)
        : get(`/api/papers/${encodeURIComponent(paperId)}`),
    chunkDetail: (chunkId: string): Promise<ChunkDetailData> =>
      fixtureMode
        ? Promise.resolve(chunkDetailFixture)
        : get(`/api/chunks/${encodeURIComponent(chunkId)}`),
    search: (input: SearchInput): Promise<McpEnvelope<SearchData>> =>
      fixtureMode ? Promise.resolve(searchFixture) : post("/api/search", input),
    qa: (input: QaInput): Promise<McpEnvelope<QaData>> =>
      fixtureMode ? Promise.resolve(fixtureQaEnvelope(input)) : post("/api/qa", input),
    qaStream: async (input: QaInput, onEvent: QaStreamHandler): Promise<void> => {
      if (fixtureMode) {
        const envelope = fixtureQaEnvelope(input);
        for (const event of qaStreamEventsFixture) {
          const next = clone(event);
          if (next.event === "done" && envelope.data) {
            next.data.note_refs = envelope.data.note_refs;
            next.data.context_policy = envelope.data.context_policy;
            next.data.project_context_warnings = envelope.data.project_context_warnings;
          }
          onEvent(next);
        }
        return;
      }
      return streamPaperQa({
        url: `${baseUrl}/api/qa/stream`,
        fetcher: fetchImpl,
        body: input,
        onEvent,
      });
    },
    section: (input: SectionInput): Promise<McpEnvelope<SectionData>> =>
      fixtureMode ? Promise.resolve(sectionFixture) : post("/api/section", input),
    discover: (input: DiscoverInput): Promise<McpEnvelope<DiscoverData>> =>
      fixtureMode ? Promise.resolve(discoverFixture) : post("/api/discover", input),
    ingestCandidates: (input: CandidateIngestInput): Promise<McpEnvelope<IngestData>> =>
      fixtureMode ? Promise.resolve(ingestFixture) : post("/api/ingest/candidates", input),
    dshHandoff: (input: DshHandoffInput): Promise<DshHandoffData> =>
      fixtureMode ? Promise.resolve(dshHandoffFixture) : post("/api/dsh/handoff", input),
    projects: (includeArchived = false): Promise<{ projects: ProjectSummary[] }> =>
      fixtureMode
        ? Promise.resolve({
            projects: fixtureProjectList().filter(
              (project) => includeArchived || project.status === "active",
            ),
          })
        : get(`/api/projects?include_archived=${encodeURIComponent(includeArchived)}`),
    createProject: (input: ProjectCreateInput): Promise<{ project: ProjectSummary }> => {
      if (!fixtureMode) return post("/api/projects", input);
      const project: ProjectSummary = {
        project_id: `project-${fixtureDetails.size + 1}`,
        name: input.name,
        description: input.description ?? "",
        status: "active",
        created_at: nowFixture(),
        updated_at: nowFixture(),
      };
      fixtureDetails.set(project.project_id, {
        project,
        summary: {
          paper_count: 0,
          evidence_count: 0,
          note_count: 0,
          saved_question_count: 0,
          compare_run_count: 0,
        },
        papers: [],
        evidence: [],
        notes: [],
        saved_questions: [],
        compare_runs: [],
        warnings: [],
      });
      return Promise.resolve({ project: clone(project) });
    },
    project: (projectId: string): Promise<ProjectDetail> =>
      fixtureMode ? Promise.resolve(clone(fixtureProject(projectId))) : get(`/api/projects/${projectId}`),
    updateProject: (
      projectId: string,
      input: ProjectUpdateInput,
    ): Promise<{ project: ProjectSummary }> => {
      if (!fixtureMode) return patch(`/api/projects/${projectId}`, input);
      const detail = fixtureProject(projectId);
      detail.project = {
        ...detail.project,
        name: input.name ?? detail.project.name,
        description: input.description ?? detail.project.description,
        updated_at: nowFixture(),
      };
      return Promise.resolve({ project: clone(detail.project) });
    },
    archiveProject: (projectId: string): Promise<{ project: ProjectSummary }> => {
      if (!fixtureMode) return post(`/api/projects/${projectId}/archive`, {});
      const detail = fixtureProject(projectId);
      detail.project.status = "archived";
      detail.project.updated_at = nowFixture();
      return Promise.resolve({ project: clone(detail.project) });
    },
    addProjectPaper: (
      projectId: string,
      input: ProjectPaperInput,
    ): Promise<{ paper: ProjectDetail["papers"][number] }> => {
      if (!fixtureMode) return post(`/api/projects/${projectId}/papers`, input);
      const detail = fixtureProject(projectId);
      const existing = detail.papers.find((paper) => paper.paper_id === input.paper_id);
      const paper =
        existing ??
        {
          project_id: projectId,
          paper_id: input.paper_id,
          title_snapshot: input.title_snapshot ?? "",
          source: input.source ?? "manual",
          created_at: nowFixture(),
        };
      paper.title_snapshot = input.title_snapshot ?? paper.title_snapshot;
      paper.source = input.source ?? paper.source;
      if (!existing) detail.papers.unshift(paper);
      refreshSummary(detail);
      return Promise.resolve({ paper: clone(paper) });
    },
    pinEvidence: (
      projectId: string,
      input: EvidencePinInput,
    ): Promise<{ evidence: ProjectDetail["evidence"][number] }> => {
      if (!fixtureMode) return post(`/api/projects/${projectId}/evidence`, input);
      const detail = fixtureProject(projectId);
      const existing = detail.evidence.find((pin) => pin.chunk_id === input.chunk_id);
      const evidence =
        existing ??
        {
          pin_id: `pin-${detail.evidence.length + 1}`,
          project_id: projectId,
          chunk_id: input.chunk_id,
          paper_id: input.paper_id,
          label: input.label ?? "",
          note: input.note ?? "",
          source: input.source ?? "manual",
          score_snapshot: input.score_snapshot,
          quote_snapshot: input.quote_snapshot ?? "",
          created_at: nowFixture(),
          updated_at: nowFixture(),
        };
      evidence.paper_id = input.paper_id;
      evidence.label = input.label ?? evidence.label;
      evidence.note = input.note ?? evidence.note;
      evidence.source = input.source ?? evidence.source;
      evidence.score_snapshot = input.score_snapshot ?? evidence.score_snapshot;
      evidence.quote_snapshot = input.quote_snapshot ?? evidence.quote_snapshot;
      evidence.updated_at = nowFixture();
      if (!existing) detail.evidence.unshift(evidence);
      refreshSummary(detail);
      return Promise.resolve({ evidence: clone(evidence) });
    },
    createNote: (projectId: string, input: NoteInput): Promise<{ note: ProjectDetail["notes"][number] }> => {
      if (!fixtureMode) return post(`/api/projects/${projectId}/notes`, input);
      const detail = fixtureProject(projectId);
      const existing = input.note_id
        ? detail.notes.find((note) => note.note_id === input.note_id)
        : undefined;
      const note =
        existing ??
        {
          note_id: input.note_id ?? `note-${detail.notes.length + 1}`,
          project_id: projectId,
          target_type: input.target_type,
          target_id: input.target_id,
          body: input.body,
          created_at: nowFixture(),
          updated_at: nowFixture(),
        };
      note.target_type = input.target_type;
      note.target_id = input.target_id;
      note.body = input.body;
      note.updated_at = nowFixture();
      if (!existing) detail.notes.unshift(note);
      refreshSummary(detail);
      return Promise.resolve({ note: clone(note) });
    },
    saveQuestion: (
      projectId: string,
      input: SavedQuestionInput,
    ): Promise<{ question: ProjectDetail["saved_questions"][number] }> => {
      if (!fixtureMode) return post(`/api/projects/${projectId}/questions`, input);
      const detail = fixtureProject(projectId);
      const question = {
        question_id: `question-${detail.saved_questions.length + 1}`,
        project_id: projectId,
        question: input.question,
        answer: input.answer,
        citations: input.citations,
        chunk_ids: input.chunk_ids,
        citation_papers: input.citation_papers ?? {},
        trace_id: input.trace_id ?? null,
        abstain: input.abstain,
        context_policy: input.context_policy ?? null,
        created_at: nowFixture(),
      };
      detail.saved_questions.unshift(question);
      refreshSummary(detail);
      return Promise.resolve({ question: clone(question) });
    },
    projectDshHandoff: (
      projectId: string,
      input: ProjectHandoffInput,
    ): Promise<DshHandoffData> => {
      if (!fixtureMode) return post(`/api/projects/${projectId}/dsh-handoff`, input);
      const detail = fixtureProject(projectId);
      const prompt = [
        "基于 Paper RAG Workbench 当前项目继续研究。",
        "",
        `项目: ${detail.project.name}`,
        input.instruction ? `任务: ${input.instruction}` : "",
        "论文:",
        ...detail.papers.map((paper) => `- ${paper.paper_id}: ${paper.title_snapshot}`),
        "证据:",
        ...detail.evidence.map((pin) => `- ${pin.paper_id} / ${pin.chunk_id}: ${pin.quote_snapshot}`),
        "笔记:",
        ...detail.notes.map((note) => `- ${note.target_type}:${note.target_id}: ${note.body}`),
        "",
        "请使用 Paper RAG 工具核查关键结论，所有论文事实保留证据引用。",
      ]
        .filter(Boolean)
        .join("\n");
      return Promise.resolve({
        dsh_url: "http://127.0.0.1:3080",
        prompt,
        handoff: {
          handoff_id: `handoff-${Date.now()}`,
          project_id: projectId,
          prompt,
          paper_ids: detail.papers.map((paper) => paper.paper_id),
          chunk_ids: detail.evidence.map((pin) => pin.chunk_id),
          question_ids: detail.saved_questions.map((question) => question.question_id),
          created_at: nowFixture(),
        },
      });
    },
    createCompareRun: (
      projectId: string,
      input: CompareInput,
    ): Promise<{ run: CompareRun }> => {
      if (!fixtureMode) return post(`/api/projects/${projectId}/compare`, input);
      const detail = fixtureProject(projectId);
      const run = buildFixtureCompareRun(projectId, input);
      detail.compare_runs.unshift(run);
      refreshSummary(detail);
      return Promise.resolve({ run: clone(run) });
    },
    compareRuns: (projectId: string): Promise<{ runs: CompareRun[] }> =>
      fixtureMode
        ? Promise.resolve({ runs: clone(fixtureProject(projectId).compare_runs) })
        : get(`/api/projects/${projectId}/compare-runs`),
    compareRun: (projectId: string, runId: string): Promise<{ run: CompareRun }> => {
      if (!fixtureMode) return get(`/api/projects/${projectId}/compare-runs/${runId}`);
      const run = fixtureProject(projectId).compare_runs.find((item) => item.run_id === runId);
      if (!run) throw new Error(`Fixture compare run not found: ${runId}`);
      return Promise.resolve({ run: clone(run) });
    },
    compareDshHandoff: (projectId: string, runId: string): Promise<DshHandoffData> => {
      if (!fixtureMode) {
        return post(`/api/projects/${projectId}/compare-runs/${runId}/dsh-handoff`, {});
      }
      const run = fixtureProject(projectId).compare_runs.find((item) => item.run_id === runId);
      if (!run) throw new Error(`Fixture compare run not found: ${runId}`);
      const prompt = [
        "Continue from this Paper RAG Workbench Compare run.",
        "",
        `Compare run: ${run.run_id}`,
        `Dimensions: ${run.dimensions.join(", ")}`,
        ...run.cells.map(
          (cell) =>
            `- ${cell.paper_id} / ${cell.dimension}: ${cell.summary} | evidence: ${
              cell.evidence_chunk_ids.join(", ") || "No pinned evidence"
            }`,
        ),
      ].join("\n");
      return Promise.resolve({
        dsh_url: "http://127.0.0.1:3080",
        prompt,
        handoff: {
          handoff_id: `handoff-${Date.now()}`,
          project_id: projectId,
          prompt,
          paper_ids: run.paper_ids,
          chunk_ids: Array.from(
            new Set(run.cells.flatMap((cell) => cell.evidence_chunk_ids)),
          ),
          question_ids: [],
          created_at: nowFixture(),
        },
      });
    },
  };
}

export const workbenchClient = createWorkbenchClient();

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function nowFixture(): string {
  return new Date().toISOString();
}
