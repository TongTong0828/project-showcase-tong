import { useI18n } from "../i18n";
import type { Candidate } from "../types";

export function CandidateTable({
  candidates,
  selectedIds,
  onToggle,
}: {
  candidates: Candidate[];
  selectedIds: number[];
  onToggle: (id: number) => void;
}) {
  const { t } = useI18n();
  if (candidates.length === 0) {
    return (
      <div className="table-empty" role="status">
        {t("candidate.empty")}
      </div>
    );
  }

  return (
    <div className="table-frame">
      <table className="data-table">
        <thead>
          <tr>
            <th>{t("candidate.select")}</th>
            <th>{t("candidate.candidate")}</th>
            <th>{t("candidate.source")}</th>
            <th>{t("candidate.rank")}</th>
            <th>{t("candidate.evidence")}</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate) => (
            <tr key={candidate.id} className={selectedIds.includes(candidate.id) ? "selected-row" : ""}>
              <td>
                <input
                  aria-label={t("candidate.selectAria", { id: candidate.id })}
                  checked={selectedIds.includes(candidate.id)}
                  type="checkbox"
                  onChange={() => onToggle(candidate.id)}
                />
              </td>
              <td>
                <strong>{candidate.title}</strong>
                <div className="muted">id {candidate.id}</div>
                <div>{candidate.rank_reason ?? candidate.reason ?? ""}</div>
              </td>
              <td>{candidate.source ?? ""}</td>
              <td>{candidate.rank ?? ""}</td>
              <td>{t("candidate.notEvidence")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
