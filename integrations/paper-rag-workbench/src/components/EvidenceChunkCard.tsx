import { useI18n } from "../i18n";
import type { EvidenceChunk } from "../types";
import { useOptionalProjectContext } from "../context/ProjectContext";
import { PinEvidenceButton } from "./PinEvidenceButton";

export function EvidenceChunkCard({
  chunk,
  onInspect,
}: {
  chunk: EvidenceChunk;
  onInspect?: (chunkId: string) => void;
}) {
  const { t } = useI18n();
  const project = useOptionalProjectContext();
  const title = chunk.title ?? chunk.paper_title ?? chunk.paper_id;
  const text = chunk.text ?? chunk.snippet ?? "";
  const paperSaved = Boolean(
    project?.activeProject?.papers.some((paper) => paper.paper_id === chunk.paper_id),
  );

  const addPaper = async () => {
    await project?.addPaper({
      paper_id: chunk.paper_id,
      title_snapshot: title,
      source: "search",
    });
  };

  return (
    <article className="evidence-card">
      <header>
        <strong>{title}</strong>
        <span>{chunk.paper_id}</span>
        {chunk.page !== undefined ? <span>{t("chunk.page", { page: chunk.page })}</span> : null}
      </header>
      <p>{text}</p>
      <footer>
        <code>chunk:{chunk.chunk_id}</code>
        {chunk.score !== undefined ? (
          <span>{t("chunk.score", { score: chunk.score.toFixed(2) })}</span>
        ) : null}
        {onInspect ? (
          <button type="button" onClick={() => onInspect(chunk.chunk_id)}>
            {t("chunk.inspect", { id: chunk.chunk_id })}
          </button>
        ) : null}
        {project?.activeProjectId ? (
          <button
            type="button"
            aria-label={
              paperSaved
                ? `${t("workspace.inProject")} ${title}`
                : t("paperTable.addProjectAria", { title })
            }
            onClick={addPaper}
            disabled={paperSaved}
          >
            {paperSaved ? t("workspace.inProject") : t("paperTable.addProject")}
          </button>
        ) : null}
        <PinEvidenceButton chunk={chunk} />
      </footer>
    </article>
  );
}
