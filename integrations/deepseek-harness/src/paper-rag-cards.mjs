const MAX_CARD_TEXT = 1800;
const MAX_FIELD_TEXT = 280;
const MAX_ITEMS = 5;

/** @typedef {import("@deepseek-ai/dsh-llm").ContentBlock} ContentBlock */
/** @typedef {import("@deepseek-ai/dsh-tools").ToolResultView} ToolResultView */

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

const TITLE_BY_TYPE = Object.freeze({
  artifact_delivery: "Artifact Delivery",
  corpus_status: "Corpus Status",
  discovery_candidates: "Discovery Candidates",
  evidence_answer: "Evidence Answer",
  ingest_receipt: "Ingest Receipt",
  paper_rag_error: "Paper RAG Error",
  paper_rag_result: "Paper RAG Result",
});

const PRIVATE_KEYS = new Set([
  "_meta",
  "api_key",
  "authorization",
  "content_base64",
  "openai_api_key",
  "paper_rag",
  "request_boundary_id",
  "secret",
  "token",
]);

export function cardTypeForTool(toolName) {
  return CARD_BY_TOOL[toolName];
}

export function createPortableCard(toolName, args = {}, structuredContent = {}) {
  const safeStructured = sanitizeObject(structuredContent);
  const effectiveTool = safeStructured.tool ?? toolName;
  const type = safeStructured.ok === false ? "paper_rag_error" : CARD_BY_TOOL[effectiveTool] ?? "paper_rag_result";
  const data = safeStructured.data ?? {};
  const base = {
    schema_version: 1,
    type,
    tool: effectiveTool,
    title: titleFor(type),
    ok: safeStructured.ok === true,
    evidence_role: safeStructured.evidence_role ?? "none",
    trace_id: safeStructured.trace_id ?? null,
    warnings: Array.isArray(safeStructured.warnings) ? safeStructured.warnings : [],
    fields: {},
    items: [],
  };

  return populateCard(base, sanitizeObject(args), data, safeStructured);
}

export function renderPortableCardMarkdown(card) {
  const lines = [`### ${bounded(card.title, 80)}`];
  lines.push(`tool=${bounded(card.tool, 80)} ok=${card.ok === true} evidence_role=${bounded(card.evidence_role, 80)}`);
  if (card.trace_id) {
    lines.push(`trace_id=${bounded(card.trace_id, 120)}`);
  }
  for (const [key, value] of Object.entries(card.fields ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    lines.push(`${key}=${formatScalar(value)}`);
  }
  for (const warning of card.warnings ?? []) {
    lines.push(`warning=${bounded(warning, MAX_FIELD_TEXT)}`);
  }
  for (const item of card.items ?? []) {
    lines.push(`- ${renderItem(item)}`);
  }
  return bounded(lines.join("\n"), MAX_CARD_TEXT);
}

/** @returns {ContentBlock[]} */
export function renderPaperRagResultForModel(args, value, fallbackToolName = "paper_rag") {
  const structured = value?.structuredContent ?? value ?? {};
  const toolName = structured.tool ?? fallbackToolName;
  const card = createPortableCard(toolName, args, structured);
  return [textBlock(renderPortableCardMarkdown(card))];
}

/** @returns {ToolResultView | undefined} */
export function presentPaperRagResult(args, result, fallbackToolName = "paper_rag") {
  const structured = result?.meta;
  if (structured === undefined || structured === null || typeof structured !== "object") {
    return undefined;
  }
  const toolName = structured.tool ?? fallbackToolName;
  const card = createPortableCard(toolName, args, structured);
  return /** @type {ToolResultView} */ ({
    card: "generic",
    title: card.title,
    content: [textBlock(renderPortableCardMarkdown(card))],
  });
}

/** @returns {ContentBlock} */
function textBlock(text) {
  return /** @type {ContentBlock} */ ({ type: "text", text });
}

function titleFor(type) {
  return TITLE_BY_TYPE[type] ?? TITLE_BY_TYPE.paper_rag_result;
}

function populateCard(card, args, data, structured) {
  if (card.type === "paper_rag_error") {
    const error = structured.error ?? {};
    card.fields.code = error.code ?? "UNKNOWN";
    card.fields.message = error.message ?? "tool failed";
    card.fields.retryable = error.retryable === true;
    return card;
  }
  if (card.type === "corpus_status") {
    populateCorpusStatus(card, data);
  } else if (card.type === "discovery_candidates") {
    populateDiscoveryCandidates(card, data);
  } else if (card.type === "ingest_receipt") {
    populateIngestReceipt(card, args, data);
  } else if (card.type === "evidence_answer") {
    populateEvidenceAnswer(card, data);
  } else if (card.type === "artifact_delivery") {
    populateArtifactDelivery(card, data);
  } else {
    card.fields.count = data.count;
  }
  return card;
}

function populateCorpusStatus(card, data) {
  if (data.sqlite !== undefined) {
    card.fields.paper_count = data.sqlite?.paper_count;
    card.fields.chunk_count = data.sqlite?.chunk_count;
    card.fields.sqlite = data.sqlite?.available === false ? "unavailable" : "available";
  }
  if (data.llm !== undefined) {
    card.fields.chat_model = data.llm?.chat_model;
    card.fields.llm_configured = data.llm?.configured;
  }
  if (Array.isArray(data.papers)) {
    card.fields.paper_count = data.count ?? data.papers.length;
    card.items = data.papers.slice(0, MAX_ITEMS).map((paper) => ({
      paper_id: paper.paper_id,
      title: paper.title,
      arxiv_id: paper.arxiv_id,
      chunks: paper.chunk_count,
    }));
  }
}

function populateDiscoveryCandidates(card, data) {
  const candidates = Array.isArray(data.candidates) ? data.candidates : [];
  card.fields.run_id = data.run?.id ?? data.id;
  card.fields.topic = data.run?.topic ?? data.topic;
  card.fields.count = data.count ?? candidates.length;
  card.fields.evidence_notice = "Candidate-only; not Paper RAG answer evidence";
  card.items = candidates.slice(0, MAX_ITEMS).map((candidate) => ({
    id: candidate.id,
    title: candidate.title,
    source: candidate.source,
    year: candidate.year ?? candidate.published_year,
    rank: candidate.rank,
    reason: candidate.rank_reason ?? candidate.reason,
    evidence_role: candidate.evidence_role ?? "discovery_only_not_answer_evidence",
  }));
}

function populateIngestReceipt(card, args, data) {
  const results = Array.isArray(data.results) ? data.results : [data];
  card.fields.operation = card.tool;
  card.fields.source = ingestSource(args);
  card.fields.count = data.count ?? results.filter((item) => item && Object.keys(item).length > 0).length;
  card.fields.write_boundary = "approval-required";
  card.items = results
    .filter((item) => item && Object.keys(item).length > 0)
    .slice(0, MAX_ITEMS)
    .map((item) => ({
      candidate_id: item.candidate_id,
      paper_id: item.paper_id,
      status: item.status,
      chunks: item.n_chunks,
      reason: item.reason,
    }));
}

function populateEvidenceAnswer(card, data) {
  const citations = Array.isArray(data.citations) ? data.citations : [];
  const chunks = Array.isArray(data.chunks) ? data.chunks : [];
  card.fields.citation_count = citations.length;
  card.fields.citations = citations.length;
  card.fields.chunk_count = chunks.length;
  card.fields.abstain = data.abstain?.decision ?? data.abstain;
  card.fields.answer = data.answer;
  card.items = chunks.slice(0, MAX_ITEMS).map((chunk) => ({
    chunk_id: chunk.chunk_id,
    paper_id: chunk.paper_id,
    title: chunk.title ?? chunk.paper_title,
    page: chunk.page,
    text: chunk.text,
  }));
  if (data.matrix !== undefined) {
    card.fields.answer = "comparison matrix";
    card.fields.paper_count = Array.isArray(data.papers) ? data.papers.length : undefined;
    card.fields.dimension_count = Array.isArray(data.dimensions) ? data.dimensions.length : undefined;
  }
  if (data.section !== undefined) {
    card.fields.section = data.section?.name ?? data.section_name;
  }
}

function populateArtifactDelivery(card, data) {
  const artifact = data.artifact ?? {};
  card.fields.format = data.format;
  card.fields.content_type = data.content_type;
  card.fields.paper_count = data.paper_count;
  card.fields.artifact_id = artifact.artifact_id;
  card.fields.path = artifact.path;
  card.fields.manifest_path = artifact.manifest_path;
}

function ingestSource(args) {
  if (args.arxiv_id) return `arxiv:${args.arxiv_id}`;
  if (args.pdf_url) return "pdf_url";
  if (args.pdf_path) return "pdf_path";
  if (Array.isArray(args.candidate_ids)) return `candidate_ids=${args.candidate_ids.join(",")}`;
  return "unspecified";
}

function renderItem(item) {
  return Object.entries(item)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${key}=${formatScalar(value)}`)
    .join(" ");
}

function formatScalar(value) {
  if (Array.isArray(value)) {
    return bounded(value.join(","), MAX_FIELD_TEXT);
  }
  if (value !== null && typeof value === "object") {
    return bounded(JSON.stringify(sanitizeObject(value)), MAX_FIELD_TEXT);
  }
  return bounded(String(value), MAX_FIELD_TEXT);
}

function sanitizeObject(value) {
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeObject(item));
  }
  if (value === null || typeof value !== "object") {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => !PRIVATE_KEYS.has(String(key).toLowerCase()))
      .map(([key, item]) => [key, sanitizeObject(item)]),
  );
}

function bounded(value, limit) {
  const text = value === undefined || value === null ? "" : String(value);
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 3))}...`;
}
