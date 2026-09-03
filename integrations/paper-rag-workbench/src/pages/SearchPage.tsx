import { useState } from "react";

import { ChunkDetailPanel } from "../components/ChunkDetailPanel";
import { DshHandoffDialog } from "../components/DshHandoffDialog";
import { EmptyState } from "../components/EmptyState";
import { EvidenceChunkCard } from "../components/EvidenceChunkCard";
import { PaperDetailPanel } from "../components/PaperDetailPanel";
import { useI18n } from "../i18n";
import type {
  ChunkDetailData,
  DshHandoffData,
  PaperDetailData,
  SearchData,
  WorkbenchClient,
} from "../types";

export function SearchPage({ client }: { client: WorkbenchClient }) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(8);
  const [data, setData] = useState<SearchData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [chunkDetail, setChunkDetail] = useState<ChunkDetailData | null>(null);
  const [paperDetail, setPaperDetail] = useState<PaperDetailData | null>(null);
  const [handoff, setHandoff] = useState<DshHandoffData | null>(null);

  const search = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery) return;

    setError(null);
    setData(null);
    setChunkDetail(null);
    setPaperDetail(null);
    setHandoff(null);
    setLoading(true);

    try {
      const envelope = await client.search({ query: trimmedQuery, top_k: topK });
      if (!envelope.ok || !envelope.data) {
        setError(envelope.error?.message ?? t("search.unavailable"));
        return;
      }
      setData(envelope.data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("search.unavailable"));
    } finally {
      setLoading(false);
    }
  };

  const inspectChunk = async (chunkId: string) => {
    setChunkDetail(await client.chunkDetail(chunkId));
  };

  const openPaper = async (paperId: string) => {
    setPaperDetail(await client.paperDetail(paperId));
  };

  const sendSearchToDsh = async () => {
    if (!data) return;
    setHandoff(
      await client.dshHandoff({
        question: query.trim(),
        paper_ids: Array.from(new Set(data.results.map((chunk) => chunk.paper_id))),
        chunk_ids: data.results.map((chunk) => chunk.chunk_id),
        source: "search",
      }),
    );
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h2>{t("search.title")}</h2>
          <p>{t("search.subtitle")}</p>
        </div>
      </header>
      <form className="panel form-grid" onSubmit={search}>
        <label>
          <span>{t("search.evidence")}</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <label>
          <span>{t("search.topK")}</span>
          <input
            min={1}
            max={20}
            type="number"
            value={topK}
            onChange={(event) => setTopK(Number(event.target.value))}
          />
        </label>
        <button type="submit" disabled={!query.trim() || loading}>
          {loading ? t("search.loading") : t("search.submit")}
        </button>
      </form>
      {error ? <EmptyState title={t("search.unavailable")} detail={error} /> : null}
      {data ? (
        <>
          <div className="toolbar-row">
            <button type="button" onClick={sendSearchToDsh}>
              {t("search.sendToDsh")}
            </button>
          </div>
          <section className="evidence-list" aria-label={t("search.resultsAria")}>
            {data.results.map((chunk) => (
              <EvidenceChunkCard key={chunk.chunk_id} chunk={chunk} onInspect={inspectChunk} />
            ))}
          </section>
        </>
      ) : null}
      {chunkDetail ? <ChunkDetailPanel detail={chunkDetail} onOpenPaper={openPaper} /> : null}
      {paperDetail ? (
        <PaperDetailPanel detail={paperDetail} onInspectChunk={inspectChunk} />
      ) : null}
      {handoff ? <DshHandoffDialog data={handoff} onClose={() => setHandoff(null)} /> : null}
    </>
  );
}
