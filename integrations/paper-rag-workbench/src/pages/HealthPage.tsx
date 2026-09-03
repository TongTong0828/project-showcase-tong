import { useEffect, useState } from "react";

import { DshHandoffDialog } from "../components/DshHandoffDialog";
import { EmptyState } from "../components/EmptyState";
import { HealthSummary } from "../components/HealthSummary";
import { QualityIssueTable } from "../components/QualityIssueTable";
import { useI18n } from "../i18n";
import type { DshHandoffData, IndexHealthData, WorkbenchClient } from "../types";

export function HealthPage({ client }: { client: WorkbenchClient }) {
  const { t } = useI18n();
  const [data, setData] = useState<IndexHealthData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<DshHandoffData | null>(null);

  useEffect(() => {
    let cancelled = false;
    client
      .indexHealth()
      .then((next) => {
        if (!cancelled) setData(next);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : t("health.unavailable"));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client, t]);

  const sendHealthToDsh = async () => {
    if (!data) return;
    const warningText = data.warnings.length
      ? data.warnings.join("; ")
      : `Current status: ${data.status}`;
    setHandoff(
      await client.dshHandoff({
        question: `诊断这些 Paper RAG 健康信息：${warningText}`,
        paper_ids: [],
        chunk_ids: [],
        source: "health",
      }),
    );
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h2>{t("health.title")}</h2>
          <p>{t("health.subtitle")}</p>
        </div>
      </header>
      {!data && !error ? (
        <EmptyState title={t("health.loadingTitle")} detail={t("health.loadingDetail")} />
      ) : null}
      {error ? <EmptyState title={t("health.unavailable")} detail={error} /> : null}
      {data ? (
        <>
          <div className="toolbar-row">
            <button type="button" onClick={sendHealthToDsh}>
              {t("health.sendToDsh")}
            </button>
          </div>
          <HealthSummary data={data} />
          <section className="panel">
            <h3>{t("health.qualityIssues")}</h3>
            <QualityIssueTable samples={data.corpus_quality.samples} />
          </section>
          {handoff ? (
            <DshHandoffDialog data={handoff} onClose={() => setHandoff(null)} />
          ) : null}
        </>
      ) : null}
    </>
  );
}
