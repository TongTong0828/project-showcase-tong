import { useI18n } from "../i18n";
import type { PaperSummary } from "../types";

export function PaperTable({
  papers,
  onAsk,
  onSearch,
  onSection,
  onInspect,
  onAddProject,
}: {
  papers: PaperSummary[];
  onAsk: (paper: PaperSummary) => void;
  onSearch: (paper: PaperSummary) => void;
  onSection: (paper: PaperSummary) => void;
  onInspect?: (paper: PaperSummary) => void;
  onAddProject?: (paper: PaperSummary) => void;
}) {
  const { t } = useI18n();
  if (papers.length === 0) {
    return (
      <div className="table-empty" role="status">
        {t("paperTable.empty")}
      </div>
    );
  }

  return (
    <div className="table-frame">
      <table className="data-table">
        <thead>
          <tr>
            <th>{t("paperTable.title")}</th>
            <th>{t("paperTable.paperId")}</th>
            <th>{t("paperTable.arxiv")}</th>
            <th>{t("paperTable.chunks")}</th>
            <th>{t("paperTable.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {papers.map((paper) => (
            <tr key={paper.paper_id}>
              <td>{paper.title}</td>
              <td>
                <code>{paper.paper_id}</code>
              </td>
              <td>{paper.arxiv_id || ""}</td>
              <td>{paper.chunk_count ?? 0}</td>
              <td className="row-actions">
                <button
                  type="button"
                  aria-label={t("paperTable.askAria", { title: paper.title })}
                  onClick={() => onAsk(paper)}
                >
                  {t("paperTable.ask")}
                </button>
                <button
                  type="button"
                  aria-label={t("paperTable.searchAria", { title: paper.title })}
                  onClick={() => onSearch(paper)}
                >
                  {t("paperTable.search")}
                </button>
                <button
                  type="button"
                  aria-label={t("paperTable.sectionAria", { title: paper.title })}
                  onClick={() => onSection(paper)}
                >
                  {t("paperTable.section")}
                </button>
                {onInspect ? (
                  <button
                    type="button"
                    aria-label={t("paperTable.inspectAria", { title: paper.title })}
                    onClick={() => onInspect(paper)}
                  >
                    {t("paperTable.inspect")}
                  </button>
                ) : null}
                {onAddProject ? (
                  <button
                    type="button"
                    aria-label={t("paperTable.addProjectAria", { title: paper.title })}
                    onClick={() => onAddProject(paper)}
                  >
                    {t("paperTable.addProject")}
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
