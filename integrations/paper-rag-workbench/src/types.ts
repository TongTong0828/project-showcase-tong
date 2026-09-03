export type McpEnvelope<TData = Record<string, unknown>> = {
  ok: boolean;
  tool: string;
  trace_id?: string | null;
  evidence_role?: string;
  warnings?: string[];
  data?: TData;
  error?: {
    code: string;
    message: string;
    retryable?: boolean;
    details?: Record<string, unknown>;
  };
};

export type HealthData = {
  ok: boolean;
  service: string;
  dsh_url: string;
  models: { chat_model: string; small_model: string };
};

export type HealthStatus = "healthy" | "degraded" | "blocked";

export type HealthSample = {
  kind: "duplicate_chunk" | "parser_artifact" | "missing_section" | string;
  paper_id?: string;
  chunk_id?: string;
  chunk_ids?: string[];
  warnings?: string[];
  preview?: string;
};

export type IndexHealthData = {
  status: HealthStatus;
  sqlite: {
    available: boolean;
    paper_count: number;
    chunk_count: number;
    fts_available: boolean;
  };
  qdrant: {
    configured: boolean;
    mode: "server" | "embedded" | "none";
    reachable: boolean;
    collection_chunks?: string;
    degraded_reason?: string | null;
  };
  retrieval: {
    dense_available: boolean;
    sparse_available: boolean;
    hybrid_available: boolean;
  };
  llm: {
    configured: boolean;
    chat_model: string;
    base_url_host?: string | null;
    credential_source?: "env" | "file" | null;
  };
  corpus_quality: {
    duplicate_chunk_count: number;
    parser_artifact_count: number;
    missing_section_count: number;
    samples: HealthSample[];
  };
  warnings: string[];
};

export type PaperSummary = {
  paper_id: string;
  title: string;
  arxiv_id?: string | null;
  chunk_count?: number;
  ingested_at?: string;
};

export type EvidenceChunk = {
  chunk_id: string;
  paper_id: string;
  title?: string;
  paper_title?: string;
  page?: number;
  section?: string;
  snippet?: string;
  text?: string;
  score?: number;
};

export type PaperSectionSummary = {
  section_id: string;
  name: string;
  idx: number;
  page_start?: number | null;
  page_end?: number | null;
  chunk_count: number;
};

export type PaperDetailData = {
  paper: PaperSummary & {
    abstract?: string | null;
    year?: number | null;
    venue?: string | null;
    doi?: string | null;
    status?: string;
    parsed_with?: string | null;
    updated_at?: string;
  };
  sections: PaperSectionSummary[];
  chunks: EvidenceChunk[];
  warnings: string[];
};

export type ChunkDetailData = {
  chunk: EvidenceChunk & {
    warnings?: string[];
    char_start?: number | null;
    char_end?: number | null;
  };
  paper: PaperSummary;
  neighbors: EvidenceChunk[];
};

export type StatusData = {
  sqlite?: { available?: boolean; paper_count?: number; chunk_count?: number };
  llm?: { chat_model?: string; configured?: boolean };
  workbench?: {
    credentials?: { configured: boolean; source: string | null; writable: boolean };
  };
  papers?: PaperSummary[];
};

export type PaperListData = { count: number; papers: PaperSummary[] };
export type SearchData = { count: number; results: EvidenceChunk[]; truncated?: boolean };
export type QaData = {
  answer: string;
  citations: string[];
  chunks: EvidenceChunk[];
  abstain?: { decision?: string } | string;
  note_refs?: string[];
  context_policy?: ContextPolicy | Record<string, unknown>;
  project_context_warnings?: string[];
};

export type QaStreamEventName =
  | "start"
  | "intent"
  | "rewrite"
  | "retrieved"
  | "reflect"
  | "abstain"
  | "answer_chunk"
  | "done"
  | "error";

export type QaStageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export type QaStreamData = {
  trace_id?: string;
  stage?: string;
  status?: QaStageStatus;
  summary?: string;
  elapsed_ms?: number;
  text?: string;
  message?: string;
  answer?: string;
  citations?: string[];
  chunks?: EvidenceChunk[];
  abstain?: QaData["abstain"];
  n_chunks?: number;
  paper_ids?: string[];
  query_resolution?: Record<string, unknown>;
  [key: string]: unknown;
};

export type QaStreamEvent = {
  event: QaStreamEventName;
  data: QaStreamData;
};

export type QaStreamStage = {
  stage: string;
  label: string;
  status: QaStageStatus;
  summary?: string;
  elapsed_ms?: number;
  error?: string;
};

export type QaStreamState = {
  question: string;
  answer: QaData & { trace_id?: string; n_chunks?: number };
  stages: QaStreamStage[];
  done: boolean;
  error: string | null;
};

export type QaStreamHandler = (event: QaStreamEvent) => void;

export type SectionData = {
  section?: { name?: string };
  section_name?: string;
  chunks: EvidenceChunk[];
};
export type Candidate = {
  id: number;
  title: string;
  source?: string;
  year?: number;
  published_year?: number;
  rank?: number;
  rank_reason?: string;
  reason?: string;
  evidence_role?: string;
};
export type DiscoverData = { run?: { id?: number; topic?: string }; candidates: Candidate[]; count: number };
export type IngestData = {
  results: Array<{ candidate_id?: number; paper_id?: string; status?: string; n_chunks?: number }>;
  count?: number;
};

export type SearchInput = { query: string; top_k?: number; year_min?: number; year_max?: number };
export type QaInput = {
  question: string;
  paper_ids?: string[];
  resolved_question?: string;
  top_k?: number;
  project_id?: string;
  context_policy?: ContextPolicy;
};
export type SectionInput = { paper_id: string; section_name: string };
export type DiscoverInput = { topic: string; max_candidates?: number; sources?: string[] };
export type CandidateIngestInput = {
  candidate_ids: number[];
  force?: boolean;
  approval: {
    approved: true;
    operation: "discovery_candidate_ingest";
    candidate_ids: number[];
    destination: "real-library" | "isolated-library";
    side_effects: string[];
  };
};

export type DshHandoffInput = {
  question: string;
  paper_ids: string[];
  chunk_ids: string[];
  source: "ask" | "search" | "library" | "health" | "workbench";
};

export type DshHandoffData = {
  dsh_url: string;
  prompt: string;
  handoff?: ProjectHandoff;
};

export type ProjectSummary = {
  project_id: string;
  name: string;
  description: string;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
};

export type ProjectPaper = {
  project_id: string;
  paper_id: string;
  title_snapshot: string;
  source: string;
  created_at: string;
};

export type EvidencePin = {
  pin_id: string;
  project_id: string;
  chunk_id: string;
  paper_id: string;
  label: string;
  note: string;
  source: string;
  score_snapshot?: number | null;
  quote_snapshot: string;
  created_at: string;
  updated_at: string;
};

export type ResearchNote = {
  note_id: string;
  project_id: string;
  target_type: "project" | "paper" | "chunk";
  target_id: string;
  body: string;
  created_at: string;
  updated_at: string;
};

export type ContextPolicy = {
  include_pinned_evidence: boolean;
  include_notes: boolean;
  restrict_to_project_papers: boolean;
};

export type SavedQuestion = {
  question_id: string;
  project_id: string;
  question: string;
  answer: string;
  citations: string[];
  chunk_ids: string[];
  citation_papers?: Record<string, string>;
  trace_id?: string | null;
  abstain?: QaData["abstain"];
  context_policy?: ContextPolicy | Record<string, unknown> | null;
  created_at: string;
};

export type CompareCell = {
  paper_id: string;
  dimension: string;
  summary: string;
  evidence_chunk_ids: string[];
  note_ids: string[];
  confidence: "evidence_backed" | "partial" | "missing";
};

export type CompareRun = {
  run_id: string;
  project_id: string;
  dimensions: string[];
  paper_ids: string[];
  status: "completed" | "degraded";
  cells: CompareCell[];
  warnings: string[];
  created_at?: string;
};

export type ProjectSummaryCounts = {
  paper_count: number;
  evidence_count: number;
  note_count: number;
  saved_question_count: number;
  compare_run_count: number;
};

export type ProjectDetail = {
  project: ProjectSummary;
  summary: ProjectSummaryCounts;
  papers: ProjectPaper[];
  evidence: EvidencePin[];
  notes: ResearchNote[];
  saved_questions: SavedQuestion[];
  compare_runs: CompareRun[];
  warnings: string[];
};

export type ProjectHandoff = {
  handoff_id: string;
  project_id: string;
  prompt: string;
  paper_ids: string[];
  chunk_ids: string[];
  question_ids: string[];
  created_at: string;
};

export type ProjectCreateInput = { name: string; description?: string };
export type ProjectUpdateInput = { name?: string; description?: string };
export type ProjectPaperInput = {
  paper_id: string;
  title_snapshot?: string;
  source?: string;
};
export type EvidencePinInput = {
  chunk_id: string;
  paper_id: string;
  quote_snapshot?: string;
  source?: string;
  score_snapshot?: number | null;
  label?: string;
  note?: string;
};
export type NoteInput = {
  target_type: ResearchNote["target_type"];
  target_id: string;
  body: string;
  note_id?: string;
};
export type SavedQuestionInput = {
  question: string;
  answer: string;
  citations: string[];
  chunk_ids: string[];
  citation_papers?: Record<string, string>;
  trace_id?: string | null;
  abstain?: QaData["abstain"];
  context_policy?: ContextPolicy | Record<string, unknown> | null;
};
export type ProjectHandoffInput = {
  instruction?: string;
};
export type CompareInput = {
  paper_ids: string[];
  dimensions: string[];
};

export type WorkbenchClient = {
  health(): Promise<HealthData>;
  indexHealth(): Promise<IndexHealthData>;
  status(): Promise<McpEnvelope<StatusData>>;
  papers(limit?: number): Promise<McpEnvelope<PaperListData>>;
  paperDetail(paperId: string): Promise<PaperDetailData>;
  chunkDetail(chunkId: string): Promise<ChunkDetailData>;
  search(input: SearchInput): Promise<McpEnvelope<SearchData>>;
  qa(input: QaInput): Promise<McpEnvelope<QaData>>;
  qaStream(input: QaInput, onEvent: QaStreamHandler): Promise<void>;
  section(input: SectionInput): Promise<McpEnvelope<SectionData>>;
  discover(input: DiscoverInput): Promise<McpEnvelope<DiscoverData>>;
  ingestCandidates(input: CandidateIngestInput): Promise<McpEnvelope<IngestData>>;
  dshHandoff(input: DshHandoffInput): Promise<DshHandoffData>;
  projects(includeArchived?: boolean): Promise<{ projects: ProjectSummary[] }>;
  createProject(input: ProjectCreateInput): Promise<{ project: ProjectSummary }>;
  project(projectId: string): Promise<ProjectDetail>;
  updateProject(
    projectId: string,
    input: ProjectUpdateInput,
  ): Promise<{ project: ProjectSummary }>;
  archiveProject(projectId: string): Promise<{ project: ProjectSummary }>;
  addProjectPaper(
    projectId: string,
    input: ProjectPaperInput,
  ): Promise<{ paper: ProjectPaper }>;
  pinEvidence(projectId: string, input: EvidencePinInput): Promise<{ evidence: EvidencePin }>;
  createNote(projectId: string, input: NoteInput): Promise<{ note: ResearchNote }>;
  saveQuestion(
    projectId: string,
    input: SavedQuestionInput,
  ): Promise<{ question: SavedQuestion }>;
  projectDshHandoff(
    projectId: string,
    input: ProjectHandoffInput,
  ): Promise<DshHandoffData>;
  createCompareRun(projectId: string, input: CompareInput): Promise<{ run: CompareRun }>;
  compareRuns(projectId: string): Promise<{ runs: CompareRun[] }>;
  compareRun(projectId: string, runId: string): Promise<{ run: CompareRun }>;
  compareDshHandoff(projectId: string, runId: string): Promise<DshHandoffData>;
};
