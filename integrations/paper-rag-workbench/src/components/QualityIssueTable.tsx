import { useI18n } from "../i18n";
import type { HealthSample } from "../types";

export function QualityIssueTable({ samples }: { samples: HealthSample[] }) {
  const { t } = useI18n();
  if (samples.length === 0) {
    return <p className="muted">{t("quality.empty")}</p>;
  }
  return (
    <table className="quality-table">
      <thead>
        <tr>
          <th>{t("quality.kind")}</th>
          <th>{t("quality.paper")}</th>
          <th>{t("quality.chunks")}</th>
          <th>{t("quality.preview")}</th>
        </tr>
      </thead>
      <tbody>
        {samples.map((sample, index) => (
          <tr key={`${sample.kind}-${sample.chunk_id || sample.chunk_ids?.join("-") || index}`}>
            <td>{sample.kind}</td>
            <td>{sample.paper_id || t("status.unknown")}</td>
            <td>{sample.chunk_id || sample.chunk_ids?.join(", ") || t("status.unknown")}</td>
            <td>{sample.preview || sample.warnings?.join(", ") || ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
