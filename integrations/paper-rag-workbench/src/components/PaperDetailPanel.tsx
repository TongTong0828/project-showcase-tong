import { useI18n } from "../i18n";
import { useOptionalProjectContext } from "../context/ProjectContext";
import type { NoteInput, PaperDetailData } from "../types";
import { NoteEditor } from "./NoteEditor";
import { PinEvidenceButton } from "./PinEvidenceButton";

export function PaperDetailPanel({
  detail,
  onInspectChunk,
}: {
  detail: PaperDetailData;
  onInspectChunk: (chunkId: string) => void;
}) {
  const { t } = useI18n();
  const project = useOptionalProjectContext();
  const inProject = Boolean(
    project?.activeProject?.papers.some(
      (paper) => paper.paper_id === detail.paper.paper_id,
    ),
  );

  const addPaper = async () => {
    await project?.addPaper({
      paper_id: detail.paper.paper_id,
      title_snapshot: detail.paper.title,
      source: "paper_detail",
    });
  };

  const saveNote = async (input: NoteInput) => {
    await project?.createNote(input);
  };

  return (
    <section className="paper-detail panel">
      <header>
        <div>
          <h3>{detail.paper.title}</h3>
          <code>{detail.paper.paper_id}</code>
        </div>
        {project?.activeProjectId ? (
          <button
            type="button"
            aria-label={
              inProject
                ? `${t("workspace.inProject")} ${detail.paper.title}`
                : t("paperTable.addProjectAria", { title: detail.paper.title })
            }
            onClick={addPaper}
            disabled={inProject}
          >
            {inProject ? t("workspace.inProject") : t("paperTable.addProject")}
          </button>
        ) : null}
      </header>
      {detail.warnings.length ? (
        <div className="inline-warnings">
          {detail.warnings.map((warning) => (
            <span key={warning}>{warning}</span>
          ))}
        </div>
      ) : null}
      {detail.paper.abstract ? <p>{detail.paper.abstract}</p> : null}
      {project?.activeProjectId ? (
        <section className="paper-detail-actions">
          <h4>{t("workspace.addNote")}</h4>
          <NoteEditor
            targetType="paper"
            targetId={detail.paper.paper_id}
            onSave={saveNote}
          />
        </section>
      ) : null}
      <section>
        <h4>{t("paperDetail.sections")}</h4>
        <ul className="section-list">
          {detail.sections.map((section) => (
            <li key={section.section_id}>
              <strong>{section.name}</strong>
              <span>{t("paperDetail.chunkCount", { count: section.chunk_count })}</span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h4>{t("paperDetail.chunks")}</h4>
        <div className="chunk-list">
          {detail.chunks.map((chunk) => {
            const enrichedChunk = {
              ...chunk,
              paper_id: chunk.paper_id || detail.paper.paper_id,
              title: chunk.title ?? detail.paper.title,
            };
            return (
              <article className="chunk-list-item" key={chunk.chunk_id}>
                <button type="button" onClick={() => onInspectChunk(chunk.chunk_id)}>
                  <span>{chunk.section || t("paperDetail.unknownSection")}</span>
                  <code>chunk:{chunk.chunk_id}</code>
                  <span>{chunk.snippet || chunk.text}</span>
                </button>
                {project?.activeProjectId ? (
                  <div className="chunk-actions">
                    <PinEvidenceButton chunk={enrichedChunk} source="paper_detail" />
                    <NoteEditor
                      targetType="chunk"
                      targetId={chunk.chunk_id}
                      onSave={saveNote}
                    />
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>
    </section>
  );
}
