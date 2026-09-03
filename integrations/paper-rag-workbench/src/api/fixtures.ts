import type {
  ChunkDetailData,
  DiscoverData,
  DshHandoffData,
  IndexHealthData,
  IngestData,
  McpEnvelope,
  PaperDetailData,
  PaperListData,
  ProjectDetail,
  ProjectSummary,
  QaData,
  QaStreamEvent,
  QaStreamStage,
  SearchData,
  SectionData,
  StatusData,
} from "../types";

export const statusFixture: McpEnvelope<StatusData> = {
  ok: true,
  tool: "paper_status",
  evidence_role: "metadata",
  warnings: [],
  data: {
    sqlite: { available: true, paper_count: 8, chunk_count: 345 },
    llm: { chat_model: "deepseek-v4-flash", configured: true },
    workbench: { credentials: { configured: true, source: "file", writable: true } },
  },
};

export const papersFixture: McpEnvelope<PaperListData> = {
  ok: true,
  tool: "paper_list",
  evidence_role: "metadata",
  warnings: [],
  data: {
    count: 2,
    papers: [
      {
        paper_id: "arxiv:2310.11511",
        title: "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
        arxiv_id: "2310.11511",
        chunk_count: 58,
      },
      {
        paper_id: "arxiv:2005.11401",
        title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        arxiv_id: "2005.11401",
        chunk_count: 42,
      },
    ],
  },
};

export const searchFixture: McpEnvelope<SearchData> = {
  ok: true,
  tool: "paper_search",
  evidence_role: "indexed_chunks",
  warnings: [],
  data: {
    count: 2,
    results: [
      {
        chunk_id: "chunk-self-rag-1",
        paper_id: "arxiv:2310.11511",
        title: "Self-RAG",
        page: 3,
        snippet: "SELF-RAG retrieves passages on demand for supported generation.",
        score: 0.92,
      },
      {
        chunk_id: "chunk-self-rag-2",
        paper_id: "arxiv:2310.11511",
        title: "Self-RAG",
        page: 10,
        snippet: "The model learns to retrieve, generate, and critique through reflection tokens.",
        score: 0.88,
      },
    ],
  },
};

export const qaFixture: McpEnvelope<QaData> = {
  ok: true,
  tool: "paper_qa",
  evidence_role: "indexed_chunks",
  trace_id: "trace-workbench-fixture",
  warnings: [],
  data: {
    answer:
      "Self-RAG trains a model to decide when to retrieve, then critique whether retrieved evidence supports generated claims.",
    citations: ["chunk-self-rag-1", "chunk-self-rag-2"],
    chunks: searchFixture.data!.results,
    abstain: { decision: "answer" },
  },
};

export const qaStreamEventsFixture: QaStreamEvent[] = [
  {
    event: "start",
    data: {
      trace_id: "trace-workbench-fixture",
      stage: "start",
      status: "completed",
      summary: "Started Paper RAG QA",
    },
  },
  {
    event: "intent",
    data: {
      trace_id: "trace-workbench-fixture",
      stage: "intent",
      status: "completed",
      summary: "Classified as factual",
      elapsed_ms: 2,
    },
  },
  {
    event: "retrieved",
    data: {
      trace_id: "trace-workbench-fixture",
      stage: "retrieve",
      status: "completed",
      summary: "Retrieved 2 chunks",
      elapsed_ms: 8,
      n_chunks: 2,
    },
  },
  {
    event: "answer_chunk",
    data: {
      trace_id: "trace-workbench-fixture",
      stage: "answer",
      text: "Self-RAG trains a model to decide when to retrieve",
    },
  },
  {
    event: "answer_chunk",
    data: {
      trace_id: "trace-workbench-fixture",
      stage: "answer",
      text: ", then critique whether retrieved evidence supports generated claims.",
    },
  },
  {
    event: "done",
    data: {
      trace_id: "trace-workbench-fixture",
      stage: "done",
      status: "completed",
      summary: "Paper RAG QA complete",
      answer: qaFixture.data!.answer,
      citations: qaFixture.data!.citations,
      chunks: qaFixture.data!.chunks,
      abstain: qaFixture.data!.abstain,
      n_chunks: qaFixture.data!.chunks.length,
      paper_ids: ["arxiv:2310.11511"],
      query_resolution: { effective_question: "What is Self-RAG?" },
    },
  },
];

export const qaStreamFixture: { stages: QaStreamStage[] } = {
  stages: [
    {
      stage: "intent",
      label: "Understanding question",
      status: "completed",
      summary: "Classified as factual",
      elapsed_ms: 2,
    },
    {
      stage: "retrieve",
      label: "Retrieving evidence",
      status: "completed",
      summary: "Retrieved 2 chunks",
      elapsed_ms: 8,
    },
    {
      stage: "answer",
      label: "Generating answer",
      status: "completed",
      summary: "Generated answer",
    },
  ],
};

export const sectionFixture: McpEnvelope<SectionData> = {
  ok: true,
  tool: "paper_section",
  evidence_role: "indexed_chunks",
  warnings: [],
  data: {
    section: { name: "Introduction" },
    chunks: searchFixture.data!.results,
  },
};

export const discoverFixture: McpEnvelope<DiscoverData> = {
  ok: true,
  tool: "paper_discover",
  evidence_role: "discovery_only",
  warnings: [],
  data: {
    run: { id: 7, topic: "agentic rag" },
    count: 2,
    candidates: [
      {
        id: 11,
        title: "Agentic Retrieval for Language Models",
        source: "arxiv",
        year: 2026,
        rank: 1,
        rank_reason: "retrieval planning focus",
        evidence_role: "discovery_only_not_answer_evidence",
      },
      {
        id: 12,
        title: "Evaluating Self-Reflective RAG",
        source: "arxiv",
        year: 2025,
        rank: 2,
        rank_reason: "evaluation focus",
        evidence_role: "discovery_only_not_answer_evidence",
      },
    ],
  },
};

export const ingestFixture: McpEnvelope<IngestData> = {
  ok: true,
  tool: "discovery_candidate_ingest",
  evidence_role: "metadata",
  warnings: [],
  data: {
    count: 1,
    results: [
      {
        candidate_id: 11,
        paper_id: "arxiv:2601.00001",
        status: "ingested",
        n_chunks: 39,
      },
    ],
  },
};

export const indexHealthFixture: IndexHealthData = {
  status: "degraded",
  sqlite: {
    available: true,
    paper_count: 8,
    chunk_count: 345,
    fts_available: true,
  },
  qdrant: {
    configured: true,
    mode: "server",
    reachable: false,
    collection_chunks: "paper_chunks",
    degraded_reason: "connection refused",
  },
  retrieval: {
    dense_available: false,
    sparse_available: true,
    hybrid_available: true,
  },
  llm: {
    configured: true,
    chat_model: "deepseek-v4-flash",
    base_url_host: "api.deepseek.com",
    credential_source: "file",
  },
  corpus_quality: {
    duplicate_chunk_count: 1,
    parser_artifact_count: 1,
    missing_section_count: 0,
    samples: [
      {
        kind: "duplicate_chunk",
        paper_id: "arxiv:2310.11511",
        chunk_ids: ["05e56a78", "f2d5041b"],
        preview: "SELF-RAG retrieves passages on demand.",
      },
      {
        kind: "parser_artifact",
        paper_id: "arxiv:2310.11511",
        chunk_id: "chunk-self-rag-1",
        warnings: ["html_comment"],
        preview: "<!-- page 2 --> Introduction text.",
      },
    ],
  },
  warnings: ["Dense retrieval is unavailable; sparse fallback is active."],
};

export const paperDetailFixture: PaperDetailData = {
  paper: {
    paper_id: "arxiv:2310.11511",
    title: "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
    arxiv_id: "2310.11511",
    year: 2023,
    abstract: "SELF-RAG trains a model to retrieve and critique evidence.",
    chunk_count: 58,
    status: "done",
    parsed_with: "pymupdf",
  },
  sections: [
    {
      section_id: "sec-abstract",
      name: "Abstract",
      idx: 0,
      page_start: 1,
      page_end: 1,
      chunk_count: 1,
    },
    {
      section_id: "sec-intro",
      name: "Introduction",
      idx: 1,
      page_start: 1,
      page_end: 2,
      chunk_count: 3,
    },
  ],
  chunks: searchFixture.data!.results,
  warnings: ["parser_artifacts_detected"],
};

export const chunkDetailFixture: ChunkDetailData = {
  chunk: {
    ...searchFixture.data!.results[0],
    text: "SELF-RAG retrieves passages on demand and critiques its own generations.",
    warnings: ["html_comment"],
  },
  paper: paperDetailFixture.paper,
  neighbors: [searchFixture.data!.results[1]],
};

export const dshHandoffFixture: DshHandoffData = {
  dsh_url: "http://127.0.0.1:3080",
  prompt:
    "基于 Paper RAG Workbench 中选定的论文/证据继续研究：\n- Papers: arxiv:2310.11511\n- Chunks: chunk-self-rag-1\n- Question: What is Self-RAG?\n请使用 Paper RAG 工具回答，并保留证据引用。",
};

export const projectFixture: ProjectSummary = {
  project_id: "project-self-rag",
  name: "Self-RAG 调研",
  description: "Evidence-first Self-RAG research workspace.",
  status: "active",
  created_at: "2026-08-15T00:00:00Z",
  updated_at: "2026-08-15T00:00:00Z",
};

export const projectDetailFixture: ProjectDetail = {
  project: projectFixture,
  summary: {
    paper_count: 2,
    evidence_count: 1,
    note_count: 1,
    saved_question_count: 1,
    compare_run_count: 0,
  },
  papers: [
    {
      project_id: projectFixture.project_id,
      paper_id: "arxiv:2310.11511",
      title_snapshot: "Self-RAG",
      source: "library",
      created_at: "2026-08-15T00:00:00Z",
    },
    {
      project_id: projectFixture.project_id,
      paper_id: "arxiv:2005.11401",
      title_snapshot: "Retrieval-Augmented Generation",
      source: "library",
      created_at: "2026-08-15T00:00:00Z",
    },
  ],
  evidence: [
    {
      pin_id: "pin-self-rag-1",
      project_id: projectFixture.project_id,
      chunk_id: "chunk-self-rag-1",
      paper_id: "arxiv:2310.11511",
      label: "method",
      note: "",
      source: "search",
      score_snapshot: 0.92,
      quote_snapshot: "SELF-RAG retrieves passages on demand for supported generation.",
      created_at: "2026-08-15T00:00:00Z",
      updated_at: "2026-08-15T00:00:00Z",
    },
  ],
  notes: [
    {
      note_id: "note-self-rag-1",
      project_id: projectFixture.project_id,
      target_type: "chunk",
      target_id: "chunk-self-rag-1",
      body: "This is a user note, not paper evidence.",
      created_at: "2026-08-15T00:00:00Z",
      updated_at: "2026-08-15T00:00:00Z",
    },
  ],
  saved_questions: [
    {
      question_id: "question-self-rag-1",
      project_id: projectFixture.project_id,
      question: "What is Self-RAG?",
      answer: qaFixture.data!.answer,
      citations: qaFixture.data!.citations,
      chunk_ids: qaFixture.data!.chunks.map((chunk) => chunk.chunk_id),
      citation_papers: Object.fromEntries(
        qaFixture.data!.chunks.map((chunk) => [chunk.chunk_id, chunk.paper_id]),
      ),
      trace_id: "trace-workbench-fixture",
      abstain: { decision: "answer" },
      context_policy: null,
      created_at: "2026-08-15T00:00:00Z",
    },
  ],
  compare_runs: [],
  warnings: [],
};
