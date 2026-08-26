"use client";

import {
  BookOpenIcon,
  CheckIcon,
  FileTextIcon,
  InboxIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  SendIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

type InboxItem = {
  id: number;
  kind: string;
  title: string;
  body_md?: string;
  read_at?: number | null;
};

type Paper = {
  paper_id: string;
  title?: string | null;
  arxiv_id?: string | null;
  n_chunks: number;
  ingested_at?: string | null;
};

type Subscription = {
  id: number;
  kind: string;
  value: string;
  strength: string;
  enabled?: boolean | number;
};

type QASyncResponse = {
  answer: string;
  citations: string[];
  abstain: { decision?: string };
  trace_id?: string;
  n_chunks?: number;
  trace?: {
    loop?: LoopTrace;
    wiki_context?: WikiTraceContext;
    memory?: ResearchMemoryTrace;
    memory_before?: ResearchMemoryTrace;
  };
  memory?: ResearchMemoryTrace | null;
};

type WikiTraceEntry = {
  entry_id?: string;
  name?: string;
  version?: number;
  aliases?: string[];
  key_papers?: string[];
};

type WikiTraceContext = {
  role?: string;
  fingerprint?: string;
  entries?: WikiTraceEntry[];
};

type LoopIteration = {
  query?: string;
  n_retrieved?: number;
  reflect?: {
    sufficiency?: string;
    follow_up?: string;
    reason?: string;
  } | null;
};

type LoopTrace = {
  intent?: string;
  stopped_by?: string;
  iterations?: LoopIteration[];
  citations?: string[];
  n_chunks?: number;
  latency_ms?: number;
  cost?: { note?: string; llm_calls?: number | null; tokens?: number | null };
};

type ResearchMemoryTrace = {
  conversation_id?: string | null;
  recent_turns?: Array<{ question?: string; answer_preview?: string; citations?: string[] }>;
  session_summary?: string;
  research_memory?: {
    current_topics?: string[];
    read_papers?: string[];
    confirmed_findings?: string[];
    open_questions?: string[];
    preferences?: string[];
  };
  turn_count?: number;
  has_compressed_memory?: boolean;
  memory_role?: string;
};

type KnowledgeBuildStage = {
  name: string;
  status: string;
  error?: string | null;
  finished_at?: string | null;
};

type KnowledgeBuild = {
  paper_id: string;
  title?: string | null;
  arxiv_id?: string | null;
  status: string;
  error?: string | null;
  n_chunks: number;
  ingested_at?: string | null;
  stages: KnowledgeBuildStage[];
  wiki_status: string;
  wiki_consumed?: boolean;
  wiki_review_needed?: boolean;
  qdrant_status: string;
  warnings: string[];
};

type DiscoveryRun = {
  id: number;
  topic: string;
  sources: string[];
  max_candidates: number;
  status: string;
  stopped_by: string;
  created_at?: string;
};

type DiscoveryCandidate = {
  id: number;
  title?: string | null;
  paper_id?: string | null;
  arxiv_id?: string | null;
  doi?: string | null;
  score: number;
  rank?: number | null;
  selected: boolean;
  rank_reason?: string | null;
  skip_reason?: string | null;
  ingest_status: string;
};

type DiscoveryTrace = {
  trace_id?: string;
  loop?: Array<Record<string, unknown>>;
  source_errors?: Array<{ source?: string; error?: string }>;
  evidence_role?: string;
};

type DiscoveryResponse = {
  run: DiscoveryRun;
  trace: DiscoveryTrace;
  candidates: DiscoveryCandidate[];
};

type WikiResponse = {
  paper_id: string;
  summary: string;
  last_updated?: string | null;
  word_count: number;
};

type WikiGenerateResponse = {
  paper_id: string;
  status: string;
  report: Record<string, unknown>;
  wiki?: WikiResponse | null;
};

type IngestResponse = {
  paper_id: string;
  title?: string | null;
  n_chunks: number;
  status: string;
  reason?: string | null;
  merged_into?: string | null;
  wiki?: Record<string, unknown> | null;
};

type RuntimeStatus = {
  importable: boolean;
  embedding_available: boolean;
  llm_configured: boolean;
  chat_model?: string | null;
  openai_base_url_configured: boolean;
  api_key_configured: boolean;
  evidence_only: boolean;
  sqlite_available: boolean;
  sqlite_papers?: number | null;
  qdrant_available: boolean;
  qdrant_collection?: string | null;
  qdrant_points?: number | null;
  wiki_enabled?: boolean;
  wiki_available?: boolean;
  wiki_status?: string;
  wiki_reason?: string | null;
  warnings: string[];
};

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchWithAuth(`${getBackendBaseURL()}${path}`, init);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Keep the status text when the server did not return JSON.
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function isEnabled(subscription: Subscription) {
  return subscription.enabled === undefined || subscription.enabled === true || subscription.enabled === 1;
}

function ingestMessage(data: IngestResponse) {
  if (data.status === "skipped") {
    if (data.reason === "dedup" && data.merged_into) {
      return `Already indexed as ${data.merged_into}`;
    }
    return `Already indexed ${data.paper_id}`;
  }
  if (data.status === "failed") {
    return `Ingest failed for ${data.paper_id}${data.reason ? `: ${data.reason}` : ""}`;
  }
  const wikiQueued = data.wiki?.queued === true ? "; wiki queued" : "";
  return `Ingested ${data.paper_id} (${data.n_chunks} chunks${wikiQueued})`;
}

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "ok" || status === "ready" || status === "done" || status === "online" || status === "enabled") {
    return "default";
  }
  if (status === "error" || status === "failed" || status === "offline" || status === "unavailable") {
    return "destructive";
  }
  if (status === "pending" || status === "empty" || status === "skipped" || status === "disabled") {
    return "secondary";
  }
  return "outline";
}

function wikiRuntimeLabel(status?: RuntimeStatus | null) {
  if (!status?.wiki_status) return null;
  if (status.wiki_status === "enabled") return "wiki on";
  return `wiki ${status.wiki_status}`;
}

function memoryList(values?: string[]) {
  return values?.filter(Boolean).slice(0, 4) ?? [];
}

export default function PaperRagPage() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [builds, setBuilds] = useState<KnowledgeBuild[]>([]);
  const [discoveryRuns, setDiscoveryRuns] = useState<DiscoveryRun[]>([]);
  const [inbox, setInbox] = useState<InboxItem[]>([]);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [unread, setUnread] = useState(0);
  const [conversationId] = useState(() => {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
    return `paper-rag-${Date.now()}`;
  });
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<QASyncResponse | null>(null);
  const [answerQuestion, setAnswerQuestion] = useState("");
  const [newSubscription, setNewSubscription] = useState("");
  const [ingestArxiv, setIngestArxiv] = useState("");
  const [ingestPdfUrl, setIngestPdfUrl] = useState("");
  const [discoveryTopic, setDiscoveryTopic] = useState("");
  const [discovery, setDiscovery] = useState<DiscoveryResponse | null>(null);
  const [wiki, setWiki] = useState<WikiResponse | null>(null);
  const [wikiPaperId, setWikiPaperId] = useState<string | null>(null);
  const [wikiError, setWikiError] = useState<string | null>(null);
  const [wikiLoading, setWikiLoading] = useState(false);
  const [wikiGenerating, setWikiGenerating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState<"helpful" | "not_helpful" | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setError(null);
    try {
      const [paperData, buildData, discoveryData, inboxData, subsData, statusData] = await Promise.all([
        fetchJson<Paper[]>("/api/paper_rag/papers"),
        fetchJson<KnowledgeBuild[]>("/api/paper_rag/knowledge/builds"),
        fetchJson<DiscoveryRun[]>("/api/paper_rag/discovery/runs"),
        fetchJson<{ items: InboxItem[]; unread_count: number }>(
          "/api/paper_rag/inbox?unread_only=false&limit=50",
        ),
        fetchJson<Subscription[]>("/api/paper_rag/subscriptions"),
        fetchJson<RuntimeStatus>("/api/paper_rag/status"),
      ]);
      setPapers(paperData);
      setBuilds(buildData);
      setDiscoveryRuns(discoveryData);
      setInbox(inboxData.items ?? []);
      setUnread(inboxData.unread_count ?? 0);
      setSubscriptions(subsData);
      setStatus(statusData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load paper_rag");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function ask() {
    const trimmed = question.trim();
    if (!trimmed) return;
    setAsking(true);
    setAnswer(null);
    setFeedbackSent(null);
    setMessage(null);
    setError(null);
    try {
      const data = await fetchJson<QASyncResponse>("/api/paper_rag/qa/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed, conversation_id: conversationId }),
      });
      setAnswer(data);
      setAnswerQuestion(trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "QA request failed");
    } finally {
      setAsking(false);
    }
  }

  async function loadWiki(paperId: string) {
    setWikiLoading(true);
    setWiki(null);
    setWikiPaperId(paperId);
    setWikiError(null);
    setMessage(null);
    setError(null);
    try {
      const data = await fetchJson<WikiResponse>(`/api/paper_rag/wiki/${encodeURIComponent(paperId)}`);
      setWiki(data);
    } catch (err) {
      setWikiError(err instanceof Error ? err.message : "Wiki entry unavailable");
    } finally {
      setWikiLoading(false);
    }
  }

  async function generateWiki(paperId: string) {
    setWikiGenerating(true);
    setWikiError(null);
    setMessage(null);
    setError(null);
    try {
      const data = await fetchJson<WikiGenerateResponse>(
        `/api/paper_rag/wiki/${encodeURIComponent(paperId)}/generate`,
        { method: "POST" },
      );
      if (data.wiki) {
        setWiki(data.wiki);
        setMessage(`Generated wiki for ${paperId}`);
      } else {
        setWiki(null);
        setWikiError("No wiki concepts were generated from this paper yet.");
      }
    } catch (err) {
      setWikiError(err instanceof Error ? err.message : "Wiki generation failed");
    } finally {
      setWikiGenerating(false);
    }
  }

  async function ingestPaper() {
    const arxivId = ingestArxiv.trim();
    const pdfUrl = ingestPdfUrl.trim();
    if (!arxivId && !pdfUrl) return;
    setIngesting(true);
    setMessage(null);
    setError(null);
    try {
      const data = await fetchJson<IngestResponse>("/api/paper_rag/papers/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          arxiv_id: arxivId || undefined,
          pdf_url: arxivId ? undefined : pdfUrl,
        }),
      });
      setIngestArxiv("");
      setIngestPdfUrl("");
      setMessage(ingestMessage(data));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
    } finally {
      setIngesting(false);
    }
  }

  async function runDiscovery() {
    const topic = discoveryTopic.trim();
    if (!topic) return;
    setDiscovering(true);
    setMessage(null);
    setError(null);
    try {
      const data = await fetchJson<DiscoveryResponse>("/api/paper_rag/discovery/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic, sources: ["arxiv", "semantic_scholar"], max_candidates: 8 }),
      });
      setDiscovery(data);
      setMessage(`Discovery found ${data.candidates.filter((candidate) => candidate.selected).length} candidates`);
      const runs = await fetchJson<DiscoveryRun[]>("/api/paper_rag/discovery/runs");
      setDiscoveryRuns(runs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Discovery failed");
    } finally {
      setDiscovering(false);
    }
  }

  async function ingestDiscoveryCandidate(candidate: DiscoveryCandidate) {
    if (!candidate.id) return;
    setBusyId(`discover:${candidate.id}`);
    setMessage(null);
    setError(null);
    try {
      const data = await fetchJson<IngestResponse | { paper_id: string; status: string; n_chunks: number }>(
        `/api/paper_rag/discovery/candidates/${candidate.id}/ingest`,
        { method: "POST" },
      );
      setMessage(ingestMessage({ ...data, title: candidate.title, wiki: null }));
      await refresh();
      if (discovery?.run.id) {
        const refreshed = await fetchJson<DiscoveryResponse>(`/api/paper_rag/discovery/runs/${discovery.run.id}`);
        setDiscovery(refreshed);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Candidate ingest failed");
    } finally {
      setBusyId(null);
    }
  }

  async function sendFeedback(kind: "helpful" | "not_helpful") {
    if (!answer?.trace_id) return;
    setBusyId(`feedback:${kind}`);
    setError(null);
    try {
      const isHelpful = kind === "helpful";
      await fetchJson("/api/paper_rag/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_type: isHelpful ? "thumbs_up" : "thumbs_down",
          trace_id: answer.trace_id,
          payload: {
            question: answerQuestion,
            answer_preview: answer.answer.slice(0, 1000),
            citations: answer.citations.slice(0, 20),
            answer_chars: answer.answer.length,
            n_chunks: answer.n_chunks,
            ...(isHelpful ? {} : { reason: "incomplete" }),
          },
        }),
      });
      setFeedbackSent(kind);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Feedback failed");
    } finally {
      setBusyId(null);
    }
  }

  async function addSubscription() {
    const value = newSubscription.trim();
    if (!value) return;
    setError(null);
    try {
      await fetchJson("/api/paper_rag/subscriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "keyword", value, strength: "normal" }),
      });
      setNewSubscription("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Subscription failed");
    }
  }

  async function toggleSubscription(subscription: Subscription) {
    setBusyId(`sub:${subscription.id}`);
    setError(null);
    try {
      await fetchJson(`/api/paper_rag/subscriptions/${subscription.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !isEnabled(subscription) }),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Subscription update failed");
    } finally {
      setBusyId(null);
    }
  }

  async function deleteSubscription(subscription: Subscription) {
    setBusyId(`sub:${subscription.id}`);
    setError(null);
    try {
      await fetchJson(`/api/paper_rag/subscriptions/${subscription.id}`, { method: "DELETE" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Subscription delete failed");
    } finally {
      setBusyId(null);
    }
  }

  async function updateInbox(item: InboxItem, action: "read" | "dismiss") {
    setBusyId(`inbox:${item.id}`);
    setError(null);
    try {
      await fetchJson(`/api/paper_rag/inbox/${item.id}/${action}`, { method: "POST" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Inbox update failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="flex size-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-6 py-4">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <BookOpenIcon className="size-5" />
            paper_rag
          </h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            Ask indexed papers, manage ingestion, and review research signals.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Badge variant="secondary">{papers.length} papers</Badge>
          <Badge variant={unread ? "default" : "secondary"}>{unread} unread</Badge>
          {status && (
            <>
              <Badge variant={status.llm_configured ? "default" : "secondary"}>
                {status.llm_configured ? (status.chat_model ?? "LLM ready") : "evidence-only"}
              </Badge>
              {wikiRuntimeLabel(status) && (
                <Badge variant={statusVariant(status.wiki_status ?? "unavailable")}>
                  {wikiRuntimeLabel(status)}
                </Badge>
              )}
              <Badge variant={status.qdrant_available ? "secondary" : "destructive"}>
                {status.qdrant_available ? `${status.qdrant_points ?? 0} vectors` : "dense offline"}
              </Badge>
            </>
          )}
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
            <RefreshCwIcon className={loading ? "animate-spin" : ""} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
          {message && (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300">
              {message}
            </div>
          )}
          {error && (
            <div className="border-destructive/30 bg-destructive/10 text-destructive rounded-lg border px-3 py-2 text-sm">
              {error}
            </div>
          )}
          {status?.evidence_only && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
              LLM is not fully configured, so QA returns retrieved evidence only. Set OPENAI_BASE_URL,
              OPENAI_API_KEY, and CHAT_MODEL for the real DeerFlow QA demo.
            </div>
          )}
          {status?.warnings.length ? (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
              <div className="font-medium">Runtime warnings</div>
              <ul className="mt-1 list-disc space-y-1 pl-4">
                {status.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <Tabs defaultValue="ask" className="gap-4">
            <TabsList variant="line" className="flex h-auto flex-wrap justify-start">
              <TabsTrigger value="ask">Ask</TabsTrigger>
              <TabsTrigger value="knowledge">Knowledge Builder</TabsTrigger>
              <TabsTrigger value="inbox">Inbox</TabsTrigger>
              <TabsTrigger value="subscriptions">Subscriptions</TabsTrigger>
            </TabsList>

            <TabsContent value="ask" className="space-y-4">
              <div className="rounded-lg border bg-background p-3">
                <Textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="Ask about your indexed papers..."
                  className="min-h-28 resize-y border-0 bg-transparent p-0 shadow-none focus-visible:ring-0"
                  onKeyDown={(event) => {
                    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                      void ask();
                    }
                  }}
                />
                <div className="mt-3 flex items-center justify-end border-t pt-3">
                  <Button onClick={ask} disabled={asking || !question.trim()}>
                    {asking ? <Loader2Icon className="animate-spin" /> : <SendIcon />}
                    Ask
                  </Button>
                </div>
              </div>

              {answer && (
                <section className="rounded-lg border bg-background">
                  <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
                    <h2 className="text-sm font-medium">Answer</h2>
                    {answer.abstain?.decision && <Badge variant="outline">{answer.abstain.decision}</Badge>}
                    {typeof answer.n_chunks === "number" && (
                      <Badge variant="secondary">{answer.n_chunks} chunks</Badge>
                    )}
                  </div>
                  <div className="space-y-4 p-4">
                    <p className="whitespace-pre-wrap text-sm leading-6">{answer.answer}</p>
                    {answer.citations.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {answer.citations.map((citation) => (
                          <Badge key={citation} variant="outline" className="max-w-full truncate">
                            {citation}
                          </Badge>
                        ))}
                      </div>
                    )}
                    {answer.trace?.wiki_context?.entries?.length ? (
                      <div className="space-y-3 rounded-md border bg-muted/20 p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-medium">Wiki Context</h3>
                          <Badge variant="outline">
                            {answer.trace.wiki_context.role ?? "background_not_evidence"}
                          </Badge>
                          {answer.trace.wiki_context.fingerprint && (
                            <Badge variant="secondary" className="max-w-full truncate">
                              {answer.trace.wiki_context.fingerprint}
                            </Badge>
                          )}
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {answer.trace.wiki_context.entries.map((entry) => (
                            <Badge
                              key={entry.entry_id ?? entry.name}
                              variant="secondary"
                              className="max-w-full truncate"
                            >
                              {entry.name ?? entry.entry_id}
                              {typeof entry.version === "number" ? ` v${entry.version}` : ""}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {answer.trace?.loop && (
                      <div className="space-y-3 rounded-md border bg-muted/20 p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-medium">Loop Trace</h3>
                          {answer.trace.loop.intent && (
                            <Badge variant="outline">{answer.trace.loop.intent}</Badge>
                          )}
                          {answer.trace.loop.stopped_by && (
                            <Badge variant="secondary">stop: {answer.trace.loop.stopped_by}</Badge>
                          )}
                          {typeof answer.trace.loop.latency_ms === "number" && (
                            <Badge variant="secondary">{answer.trace.loop.latency_ms} ms</Badge>
                          )}
                        </div>
                        {answer.trace.loop.iterations?.length ? (
                          <div className="space-y-2">
                            {answer.trace.loop.iterations.map((iteration, index) => (
                              <div key={`${iteration.query ?? "iter"}-${index}`} className="text-sm">
                                <div className="flex flex-wrap items-center gap-2">
                                  <Badge variant="outline">round {index + 1}</Badge>
                                  {typeof iteration.n_retrieved === "number" && (
                                    <Badge variant="secondary">{iteration.n_retrieved} retrieved</Badge>
                                  )}
                                  {iteration.reflect?.sufficiency && (
                                    <Badge variant="secondary">reflect: {iteration.reflect.sufficiency}</Badge>
                                  )}
                                </div>
                                {iteration.query && (
                                  <p className="text-muted-foreground mt-1 break-words">{iteration.query}</p>
                                )}
                                {iteration.reflect?.follow_up && (
                                  <p className="text-muted-foreground mt-1 break-words">
                                    follow-up: {iteration.reflect.follow_up}
                                  </p>
                                )}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-muted-foreground text-sm">No loop iterations were recorded.</p>
                        )}
                        {answer.trace.loop.cost?.note && (
                          <p className="text-muted-foreground border-t pt-2 text-xs">{answer.trace.loop.cost.note}</p>
                        )}
                      </div>
                    )}
                    {(answer.memory ?? answer.trace?.memory) && (
                      <div className="space-y-3 rounded-md border bg-muted/20 p-3">
                        {(() => {
                          const memory = answer.memory ?? answer.trace?.memory;
                          const research = memory?.research_memory;
                          return (
                            <>
                              <div className="flex flex-wrap items-center gap-2">
                                <h3 className="text-sm font-medium">Research Memory</h3>
                                <Badge variant={memory?.has_compressed_memory ? "default" : "secondary"}>
                                  {memory?.has_compressed_memory ? "compressed" : "warming up"}
                                </Badge>
                                {typeof memory?.turn_count === "number" && (
                                  <Badge variant="secondary">{memory.turn_count} turns</Badge>
                                )}
                              </div>
                              {memory?.session_summary ? (
                                <p className="whitespace-pre-wrap text-sm leading-6">{memory.session_summary}</p>
                              ) : (
                                <p className="text-muted-foreground text-sm">
                                  Memory will compress after several turns. It guides query context only, not evidence.
                                </p>
                              )}
                              <div className="grid gap-2 text-sm md:grid-cols-2">
                                {[
                                  ["Topics", memoryList(research?.current_topics)],
                                  ["Read papers", memoryList(research?.read_papers)],
                                  ["Findings", memoryList(research?.confirmed_findings)],
                                  ["Open questions", memoryList(research?.open_questions)],
                                ].map(([label, values]) => (
                                  <div key={label as string} className="min-w-0">
                                    <div className="text-muted-foreground text-xs">{label as string}</div>
                                    {(values as string[]).length ? (
                                      <div className="mt-1 flex flex-wrap gap-1">
                                        {(values as string[]).map((value) => (
                                          <Badge key={value} variant="outline" className="max-w-full truncate">
                                            {value}
                                          </Badge>
                                        ))}
                                      </div>
                                    ) : (
                                      <p className="text-muted-foreground mt-1 text-xs">empty</p>
                                    )}
                                  </div>
                                ))}
                              </div>
                              {memory?.memory_role && (
                                <p className="text-muted-foreground border-t pt-2 text-xs">
                                  {memory.memory_role}
                                </p>
                              )}
                            </>
                          );
                        })()}
                      </div>
                    )}
                    {answer.trace_id && (
                      <div className="flex flex-wrap items-center gap-2 border-t pt-3">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void sendFeedback("helpful")}
                          disabled={busyId !== null}
                        >
                          <ThumbsUpIcon />
                          Helpful
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void sendFeedback("not_helpful")}
                          disabled={busyId !== null}
                        >
                          <ThumbsDownIcon />
                          Not helpful
                        </Button>
                        {feedbackSent && <Badge variant="secondary">feedback recorded</Badge>}
                      </div>
                    )}
                  </div>
                </section>
              )}
            </TabsContent>

            <TabsContent value="knowledge" className="space-y-4">
              <section className="space-y-3 rounded-lg border bg-background p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h2 className="text-sm font-medium">Discovery Loop</h2>
                    <p className="text-muted-foreground mt-0.5 text-xs">
                      Find candidate papers first; ingest selected papers before using them as QA evidence.
                    </p>
                  </div>
                  {discoveryRuns.length > 0 && <Badge variant="secondary">{discoveryRuns.length} runs</Badge>}
                </div>
                <div className="grid gap-2 md:grid-cols-[1fr_auto]">
                  <Input
                    value={discoveryTopic}
                    onChange={(event) => setDiscoveryTopic(event.target.value)}
                    placeholder="topic, e.g. agentic rag loop engineering"
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void runDiscovery();
                    }}
                  />
                  <Button onClick={runDiscovery} disabled={discovering || !discoveryTopic.trim()}>
                    {discovering ? <Loader2Icon className="animate-spin" /> : <SearchIcon />}
                    Discover
                  </Button>
                </div>

                {discovery && (
                  <div className="space-y-3 border-t pt-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={statusVariant(discovery.run.status)}>{discovery.run.status}</Badge>
                      <Badge variant="secondary">stop: {discovery.run.stopped_by}</Badge>
                      {discovery.trace.trace_id && <Badge variant="outline">{discovery.trace.trace_id}</Badge>}
                    </div>
                    {discovery.candidates.length === 0 ? (
                      <p className="text-muted-foreground text-sm">No candidates returned by the discovery sources.</p>
                    ) : (
                      <div className="overflow-hidden rounded-md border">
                        {discovery.candidates.map((candidate) => (
                          <div key={candidate.id} className="space-y-2 border-b px-3 py-2 last:border-b-0">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div className="min-w-0 flex-1">
                                <div className="flex min-w-0 items-center gap-2">
                                  <FileTextIcon className="text-muted-foreground size-4 shrink-0" />
                                  <p className="truncate text-sm font-medium">{candidate.title ?? candidate.paper_id}</p>
                                </div>
                                <div className="text-muted-foreground mt-1 flex flex-wrap gap-1.5 text-xs">
                                  {candidate.rank && <Badge variant="outline">rank {candidate.rank}</Badge>}
                                  <Badge variant={candidate.selected ? "default" : "secondary"}>
                                    {candidate.selected ? "selected" : candidate.skip_reason ?? "skipped"}
                                  </Badge>
                                  <Badge variant="secondary">score {candidate.score.toFixed(2)}</Badge>
                                  {candidate.paper_id && <Badge variant="outline">{candidate.paper_id}</Badge>}
                                  {candidate.arxiv_id && <Badge variant="secondary">arXiv {candidate.arxiv_id}</Badge>}
                                  <Badge variant={statusVariant(candidate.ingest_status)}>
                                    ingest {candidate.ingest_status}
                                  </Badge>
                                </div>
                              </div>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => void ingestDiscoveryCandidate(candidate)}
                                disabled={
                                  !candidate.selected ||
                                  candidate.ingest_status === "done" ||
                                  candidate.ingest_status === "skipped" ||
                                  busyId === `discover:${candidate.id}`
                                }
                              >
                                {busyId === `discover:${candidate.id}` ? (
                                  <Loader2Icon className="animate-spin" />
                                ) : (
                                  <PlusIcon />
                                )}
                                Ingest
                              </Button>
                            </div>
                            {candidate.rank_reason && (
                              <p className="text-muted-foreground break-words text-xs">{candidate.rank_reason}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    {((discovery.trace.loop?.length ?? 0) > 0 ||
                      (discovery.trace.source_errors?.length ?? 0) > 0) && (
                      <div className="space-y-2 rounded-md border bg-muted/20 p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-medium">Discovery Trace</h3>
                          {discovery.trace.evidence_role && (
                            <Badge variant="outline">{discovery.trace.evidence_role}</Badge>
                          )}
                        </div>
                        {discovery.trace.loop?.map((stage, index) => (
                          <p key={`${String(stage.stage)}-${index}`} className="text-muted-foreground text-xs">
                            {String(stage.stage)} {JSON.stringify(stage)}
                          </p>
                        ))}
                        {discovery.trace.source_errors?.map((sourceError) => (
                          <p key={`${sourceError.source}-${sourceError.error}`} className="text-destructive text-xs">
                            {sourceError.source}: {sourceError.error}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </section>

              <div className="grid gap-2 rounded-lg border bg-background p-3 md:grid-cols-[1fr_1fr_auto]">
                <Input
                  value={ingestArxiv}
                  onChange={(event) => setIngestArxiv(event.target.value)}
                  placeholder="arXiv id, e.g. 2310.11511"
                />
                <Input
                  value={ingestPdfUrl}
                  onChange={(event) => setIngestPdfUrl(event.target.value)}
                  placeholder="or direct PDF URL"
                  disabled={Boolean(ingestArxiv.trim())}
                />
                <Button onClick={ingestPaper} disabled={ingesting || (!ingestArxiv.trim() && !ingestPdfUrl.trim())}>
                  {ingesting ? <Loader2Icon className="animate-spin" /> : <PlusIcon />}
                  Ingest
                </Button>
              </div>

              {loading ? (
                <div className="text-muted-foreground flex h-32 items-center justify-center gap-2 text-sm">
                  <Loader2Icon className="size-4 animate-spin" />
                  Loading knowledge builds
                </div>
              ) : builds.length === 0 ? (
                <div className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
                  No knowledge builds yet.
                </div>
              ) : (
                <div className="overflow-hidden rounded-lg border bg-background">
                  {builds.map((build, index) => (
                    <div
                      key={build.paper_id}
                      className="space-y-3 border-b px-4 py-3 last:border-b-0"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex min-w-0 items-center gap-2">
                            <FileTextIcon className="text-muted-foreground size-4 shrink-0" />
                            <p className="truncate text-sm font-medium">{build.title ?? build.paper_id}</p>
                          </div>
                          <div className="text-muted-foreground mt-1 flex flex-wrap gap-1.5 text-xs">
                            <Badge variant="outline" className="max-w-full truncate">
                              {build.paper_id}
                            </Badge>
                            {build.arxiv_id && <Badge variant="secondary">arXiv {build.arxiv_id}</Badge>}
                            <Badge variant={statusVariant(build.status)}>{build.status}</Badge>
                            <Badge variant="secondary">{build.n_chunks} chunks</Badge>
                            <Badge variant={statusVariant(build.qdrant_status)}>qdrant {build.qdrant_status}</Badge>
                            <Badge variant={statusVariant(build.wiki_status)}>wiki {build.wiki_status}</Badge>
                            {build.wiki_consumed && <Badge variant="default">wiki consumed</Badge>}
                            {build.wiki_review_needed && <Badge variant="destructive">wiki review</Badge>}
                            <span className="sr-only">knowledge build row {index + 1}</span>
                          </div>
                        </div>
                        <Button variant="outline" size="sm" onClick={() => void loadWiki(build.paper_id)}>
                          Wiki
                        </Button>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {build.stages.map((stage) => (
                          <Badge key={stage.name} variant={statusVariant(stage.status)} className="max-w-full">
                            {stage.name}: {stage.status}
                          </Badge>
                        ))}
                      </div>
                      {build.error && <p className="text-destructive text-sm">{build.error}</p>}
                      {build.warnings.length > 0 && (
                        <ul className="text-muted-foreground list-disc space-y-1 pl-4 text-xs">
                          {build.warnings.map((warning) => (
                            <li key={warning}>{warning}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {(wikiLoading || wikiGenerating || wiki !== null || wikiPaperId !== null) && (
                <section className="rounded-lg border bg-background">
                  <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
                    <h2 className="text-sm font-medium">Wiki</h2>
                    {wikiPaperId && <Badge variant="outline">{wikiPaperId}</Badge>}
                    {wiki?.word_count ? <Badge variant="secondary">{wiki.word_count} words</Badge> : null}
                  </div>
                  <div className="p-4">
                    {wikiLoading ? (
                      <div className="text-muted-foreground flex items-center gap-2 text-sm">
                        <Loader2Icon className="size-4 animate-spin" />
                        Loading wiki
                      </div>
                    ) : wikiGenerating ? (
                      <div className="text-muted-foreground flex items-center gap-2 text-sm">
                        <Loader2Icon className="size-4 animate-spin" />
                        Generating wiki
                      </div>
                    ) : wiki ? (
                      <p className="whitespace-pre-wrap text-sm leading-6">{wiki.summary}</p>
                    ) : (
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <p className="text-muted-foreground text-sm">
                          {wikiError ?? "No wiki entry has been generated for this paper yet."}
                        </p>
                        {wikiPaperId && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => void generateWiki(wikiPaperId)}
                            disabled={wikiGenerating}
                          >
                            <PlusIcon />
                            Generate
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                </section>
              )}
            </TabsContent>

            <TabsContent value="inbox">
              {loading ? (
                <div className="text-muted-foreground flex h-32 items-center justify-center gap-2 text-sm">
                  <Loader2Icon className="size-4 animate-spin" />
                  Loading inbox
                </div>
              ) : inbox.length === 0 ? (
                <div className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
                  No paper_rag inbox cards yet.
                </div>
              ) : (
                <div className="overflow-hidden rounded-lg border bg-background">
                  {inbox.map((item) => (
                    <div key={item.id} className="flex flex-wrap items-start gap-3 border-b px-4 py-3 last:border-b-0">
                      <InboxIcon className="text-muted-foreground mt-0.5 size-4" />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium">{item.title}</p>
                          <Badge variant={item.read_at ? "secondary" : "default"}>{item.kind}</Badge>
                        </div>
                        {item.body_md && (
                          <p className="text-muted-foreground mt-1 line-clamp-3 text-sm">{item.body_md}</p>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void updateInbox(item, "read")}
                          disabled={Boolean(item.read_at) || busyId === `inbox:${item.id}`}
                        >
                          <CheckIcon />
                          Read
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void updateInbox(item, "dismiss")}
                          disabled={busyId === `inbox:${item.id}`}
                        >
                          <XIcon />
                          Dismiss
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>

            <TabsContent value="subscriptions" className="space-y-4">
              <div className="flex gap-2 rounded-lg border bg-background p-3">
                <Input
                  value={newSubscription}
                  onChange={(event) => setNewSubscription(event.target.value)}
                  placeholder="retrieval-augmented generation"
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void addSubscription();
                  }}
                />
                <Button onClick={addSubscription} disabled={!newSubscription.trim()}>
                  <PlusIcon />
                  Add
                </Button>
              </div>
              {subscriptions.length === 0 ? (
                <div className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
                  No subscriptions yet.
                </div>
              ) : (
                <div className="overflow-hidden rounded-lg border bg-background">
                  {subscriptions.map((subscription) => (
                    <div
                      key={subscription.id}
                      className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3 text-sm last:border-b-0"
                    >
                      <span className="min-w-0 flex-1 truncate">{subscription.value}</span>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{subscription.kind}</Badge>
                        <Badge variant="secondary">{subscription.strength}</Badge>
                        <Badge variant={isEnabled(subscription) ? "default" : "secondary"}>
                          {isEnabled(subscription) ? "enabled" : "paused"}
                        </Badge>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void toggleSubscription(subscription)}
                          disabled={busyId === `sub:${subscription.id}`}
                        >
                          {isEnabled(subscription) ? "Pause" : "Enable"}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void deleteSubscription(subscription)}
                          disabled={busyId === `sub:${subscription.id}`}
                        >
                          <Trash2Icon />
                          Delete
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
