import { useEffect, useMemo, useState } from "react";

import { ChunkDetailPanel } from "../components/ChunkDetailPanel";
import { DshHandoffDialog } from "../components/DshHandoffDialog";
import { EmptyState } from "../components/EmptyState";
import { PaperDetailPanel } from "../components/PaperDetailPanel";
import { PaperTable } from "../components/PaperTable";
import { useOptionalProjectContext } from "../context/ProjectContext";
import { useI18n } from "../i18n";
import type {
  ChunkDetailData,
  DshHandoffData,
  EvidenceChunk,
  PaperDetailData,
  PaperSummary,
  WorkbenchClient,
} from "../types";

export function LibraryPage({ client }: { client: WorkbenchClient }) {
  const { t } = useI18n();
  const project = useOptionalProjectContext();
  const [papers, setPapers] = useState<PaperSummary[] | null>(null);
  const [filter, setFilter] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [sectionPaper, setSectionPaper] = useState<PaperSummary | null>(null);
  const [sectionChunks, setSectionChunks] = useState<EvidenceChunk[]>([]);
  const [sectionLoading, setSectionLoading] = useState(false);
  const [paperDetail, setPaperDetail] = useState<PaperDetailData | null>(null);
  const [chunkDetail, setChunkDetail] = useState<ChunkDetailData | null>(null);
  const [handoff, setHandoff] = useState<DshHandoffData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    client
      .papers(50)
      .then((envelope) => {
        if (!active) return;
        if (!envelope.ok || !envelope.data) {
          setError(envelope.error?.message ?? t("library.unavailable"));
          return;
        }
        setPapers(envelope.data.papers);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : t("library.unavailable"));
      });

    return () => {
      active = false;
    };
  }, [client, t]);

  const filteredPapers = useMemo(() => {
    const normalized = filter.trim().toLowerCase();
    if (!papers || !normalized) return papers ?? [];

    return papers.filter((paper) =>
      [paper.title, paper.paper_id, paper.arxiv_id ?? ""].some((value) =>
        value.toLowerCase().includes(normalized),
      ),
    );
  }, [filter, papers]);

  const openSection = async (paper: PaperSummary) => {
    setMessage(null);
    setSectionPaper(paper);
    setSectionLoading(true);
    setSectionChunks([]);

    const envelope = await client.section({
      paper_id: paper.paper_id,
      section_name: "introduction",
    });

    if (!envelope.ok || !envelope.data) {
      setMessage(envelope.error?.message ?? t("library.sectionUnavailable"));
      setSectionLoading(false);
      return;
    }

    setSectionChunks(envelope.data.chunks);
    setSectionLoading(false);
  };

  const openPaperDetail = async (paper: PaperSummary) => {
    setMessage(null);
    setChunkDetail(null);
    setPaperDetail(await client.paperDetail(paper.paper_id));
  };

  const inspectChunk = async (chunkId: string) => {
    setChunkDetail(await client.chunkDetail(chunkId));
  };

  const sendPaperToDsh = async () => {
    if (!paperDetail) return;
    setHandoff(
      await client.dshHandoff({
        question: `继续研究这篇论文：${paperDetail.paper.title}`,
        paper_ids: [paperDetail.paper.paper_id],
        chunk_ids: paperDetail.chunks.slice(0, 8).map((chunk) => chunk.chunk_id),
        source: "library",
      }),
    );
  };

  const addPaperToProject = async (paper: PaperSummary) => {
    if (!project?.activeProjectId) return;
    await project.addPaper({
      paper_id: paper.paper_id,
      title_snapshot: paper.title,
      source: "library",
    });
    setMessage(t("workspace.addedPaper"));
  };

  if (error) {
    return <EmptyState title={t("library.unavailable")} detail={error} />;
  }

  if (!papers) {
    return <p className="loading">{t("library.loading")}</p>;
  }

  return (
    <>
      <header className="page-header">
        <div>
          <h2>{t("library.title")}</h2>
          <p>{t("library.subtitle")}</p>
        </div>
        <label className="filter-field">
          <span>{t("library.filter")}</span>
          <input value={filter} onChange={(event) => setFilter(event.target.value)} />
        </label>
      </header>
      <PaperTable
        papers={filteredPapers}
        onAsk={(paper) => setMessage(t("library.askReady", { title: paper.title }))}
        onSearch={(paper) => setMessage(t("library.searchReady", { title: paper.title }))}
        onSection={openSection}
        onInspect={openPaperDetail}
        onAddProject={project?.activeProjectId ? addPaperToProject : undefined}
      />
      {message ? <p className="inline-message">{message}</p> : null}
      {sectionPaper ? (
        <aside className="section-drawer" aria-label={t("library.paperSectionAria")}>
          <div>
            <span>{sectionPaper.paper_id}</span>
            <h3>{t("library.introduction")}</h3>
          </div>
          {sectionLoading ? (
            <p className="loading">{t("library.loadingSection")}</p>
          ) : (
            <div className="section-chunks">
              {sectionChunks.map((chunk) => (
                <article key={chunk.chunk_id}>
                  <span>{chunk.page ? `p${chunk.page}` : t("chunk.source")}</span>
                  <p>{chunk.snippet ?? chunk.text}</p>
                </article>
              ))}
            </div>
          )}
        </aside>
      ) : null}
      {paperDetail ? (
        <>
          <div className="toolbar-row">
            <button type="button" onClick={sendPaperToDsh}>
              {t("library.sendToDsh")}
            </button>
          </div>
          <PaperDetailPanel detail={paperDetail} onInspectChunk={inspectChunk} />
        </>
      ) : null}
      {chunkDetail ? (
        <ChunkDetailPanel
          detail={chunkDetail}
          onOpenPaper={(paperId) =>
            openPaperDetail({
              paper_id: paperId,
              title: chunkDetail.paper.title || paperId,
            })
          }
        />
      ) : null}
      {handoff ? <DshHandoffDialog data={handoff} onClose={() => setHandoff(null)} /> : null}
    </>
  );
}
