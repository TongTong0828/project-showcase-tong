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

const stringParam = (description) => ({ type: "string", description });
const stringArrayParam = (description) => ({
  type: "array",
  items: { type: "string" },
  description,
});
const numberParam = (description) => ({ type: "number", description });
const booleanParam = (description) => ({ type: "boolean", description });

const TOOL_CONFIGS = Object.freeze({
  paper_status: Object.freeze({
    description: "Inspect local Paper RAG corpus and dependency status.",
    parameters: Object.freeze({}),
  }),
  paper_list: Object.freeze({
    description: "List papers already indexed in the local shared corpus.",
    parameters: Object.freeze({
      limit: numberParam("Maximum papers to return."),
    }),
  }),
  paper_search: Object.freeze({
    description: "Search indexed paper chunks and return bounded paper matches.",
    parameters: Object.freeze({
      query: { ...stringParam("Natural-language search query."), required: true },
      top_k: numberParam("Maximum matches to return."),
      year_min: numberParam("Optional minimum publication year."),
      year_max: numberParam("Optional maximum publication year."),
    }),
  }),
  paper_qa: Object.freeze({
    description: "Answer a self-contained question from indexed chunks with citations.",
    parameters: Object.freeze({
      question: {
        ...stringParam("Self-contained research question for indexed papers."),
        required: true,
      },
      paper_ids: stringArrayParam("Optional indexed paper id constraints."),
      resolved_question: stringParam("Optional explicit self-contained resolution."),
      top_k: numberParam("Maximum evidence chunks to retrieve."),
    }),
  }),
  paper_section: Object.freeze({
    description: "Read a named section from one indexed paper.",
    parameters: Object.freeze({
      paper_id: { ...stringParam("Indexed paper id."), required: true },
      section_name: { ...stringParam("Section substring, such as limitations."), required: true },
    }),
  }),
  paper_compare: Object.freeze({
    description: "Compare up to four papers across up to four dimensions.",
    parameters: Object.freeze({
      paper_ids: { ...stringArrayParam("One to four indexed paper ids."), required: true },
      dimensions: { ...stringArrayParam("One to four comparison dimensions."), required: true },
    }),
  }),
  wiki_lookup: Object.freeze({
    description: "Look up a Paper RAG wiki concept as background metadata.",
    parameters: Object.freeze({
      concept: { ...stringParam("Concept name or alias to look up."), required: true },
    }),
  }),
  paper_discover: Object.freeze({
    description: "Discover candidate papers for a topic; candidates are not answer evidence.",
    parameters: Object.freeze({
      topic: { ...stringParam("Research topic for candidate discovery."), required: true },
      max_candidates: numberParam("Maximum candidates to return."),
      sources: stringArrayParam("Optional source names such as arxiv."),
    }),
  }),
  discovery_run_get: Object.freeze({
    description: "Fetch a prior discovery run and its candidate-only results.",
    parameters: Object.freeze({
      run_id: { ...numberParam("Discovery run id."), required: true },
    }),
  }),
  paper_ingest: Object.freeze({
    description: "Ingest one approved paper source into the configured Paper RAG corpus.",
    parameters: Object.freeze({
      arxiv_id: stringParam("Optional arXiv id. Exactly one source field is required."),
      pdf_url: stringParam("Optional PDF URL. Exactly one source field is required."),
      pdf_path: stringParam("Optional PDF path under PAPER_RAG_IMPORT_ROOT."),
      title_hint: stringParam("Optional title hint for URL or PDF path ingest."),
      force: booleanParam("Reingest even when the paper appears to exist."),
    }),
  }),
  discovery_candidate_ingest: Object.freeze({
    description: "Ingest up to five approved discovery candidates.",
    parameters: Object.freeze({
      candidate_ids: {
        type: "array",
        items: { type: "number" },
        required: true,
        description: "Candidate ids selected from paper_discover or discovery_run_get.",
      },
      force: booleanParam("Reingest even when the candidate appears to exist."),
    }),
  }),
  paper_deliver: Object.freeze({
    description: "Generate an approved deliverable artifact under the configured artifact root.",
    parameters: Object.freeze({
      format: { ...stringParam("Artifact format, such as pdf, pptx, or markdown_survey."), required: true },
      paper_ids: {
        ...stringArrayParam("One to five indexed paper ids."),
        required: true,
      },
      title: stringParam("Optional deliverable title."),
      options: {
        type: "object",
        additionalProperties: true,
        description: "Optional deliverable-specific settings.",
      },
    }),
  }),
});

export function approvalRequired(name) {
  return BROKER_WRITE_TOOL_NAMES.includes(name);
}

export function brokerToolConfig(name) {
  const config = TOOL_CONFIGS[name];
  if (config === undefined) {
    throw new Error(`unknown Paper RAG broker tool: ${name}`);
  }
  return config;
}

export function approvalReasonForTool(name, args = {}) {
  if (name === "paper_ingest") {
    return `paper_ingest writes to the configured Paper RAG corpus; source=${sourceForIngest(args)}`;
  }
  if (name === "discovery_candidate_ingest") {
    return `discovery_candidate_ingest writes approved candidates to the configured Paper RAG corpus; candidate_ids=${(args.candidate_ids ?? []).join(",")}`;
  }
  if (name === "paper_deliver") {
    return `paper_deliver writes artifact files under PAPER_RAG_ARTIFACT_ROOT; format=${args.format} paper_ids=${(args.paper_ids ?? []).join(",")}`;
  }
  return `${name} requires one-shot write approval`;
}

function sourceForIngest(args) {
  if (args.arxiv_id) return `arxiv:${args.arxiv_id}`;
  if (args.pdf_url) return "pdf_url";
  if (args.pdf_path) return "pdf_path";
  return "unspecified";
}
