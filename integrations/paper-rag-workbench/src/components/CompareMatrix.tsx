import { useI18n } from "../i18n";
import type { CompareRun } from "../types";

export function CompareMatrix({ run }: { run: CompareRun }) {
  const { t } = useI18n();

  return (
    <section className="panel compare-panel">
      <header>
        <h3>{t("compare.title")}</h3>
        <span>{run.status}</span>
      </header>
      {run.warnings.length ? (
        <div className="inline-warnings">
          {run.warnings.map((warning) => (
            <span key={warning}>{warning}</span>
          ))}
        </div>
      ) : null}
      <div className="table-frame">
        <table className="data-table compare-table">
          <thead>
            <tr>
              <th>{t("paperTable.paperId")}</th>
              {run.dimensions.map((dimension) => (
                <th key={dimension}>{dimension}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {run.paper_ids.map((paperId) => (
              <tr key={paperId}>
                <td>
                  <code>{paperId}</code>
                </td>
                {run.dimensions.map((dimension) => {
                  const cell = run.cells.find(
                    (item) => item.paper_id === paperId && item.dimension === dimension,
                  );
                  return (
                    <td key={`${paperId}-${dimension}`}>
                      <p>{cell?.summary ?? t("compare.noPinnedEvidence")}</p>
                      <small>
                        {t("compare.confidence")}: {cell?.confidence ?? "missing"}
                      </small>
                      <div className="citation-list" aria-label={t("compare.evidence")}>
                        {(cell?.evidence_chunk_ids ?? []).map((chunkId) => (
                          <code key={chunkId}>{chunkId}</code>
                        ))}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
