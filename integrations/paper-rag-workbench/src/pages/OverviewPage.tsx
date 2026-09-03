import { useEffect, useState } from "react";

import { EmptyState } from "../components/EmptyState";
import { HealthSummary } from "../components/HealthSummary";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n";
import type { IndexHealthData, StatusData, WorkbenchClient } from "../types";

export function OverviewPage({ client }: { client: WorkbenchClient }) {
  const { t } = useI18n();
  const [data, setData] = useState<StatusData | null>(null);
  const [health, setHealth] = useState<IndexHealthData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    client
      .status()
      .then((envelope) => {
        if (!active) return;
        if (!envelope.ok || !envelope.data) {
          setError(envelope.error?.message ?? t("overview.unavailable"));
          return;
        }
        setData(envelope.data);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : t("overview.unavailable"));
      });

    return () => {
      active = false;
    };
  }, [client, t]);

  useEffect(() => {
    let active = true;
    client
      .indexHealth()
      .then((next) => {
        if (active) setHealth(next);
      })
      .catch(() => {
        if (active) setHealth(null);
      });
    return () => {
      active = false;
    };
  }, [client]);

  if (error) {
    return <EmptyState title={t("overview.unavailable")} detail={error} />;
  }

  if (!data) {
    return <p className="loading">{t("overview.loading")}</p>;
  }

  const credentialsConfigured = data.workbench?.credentials?.configured ?? false;

  return (
    <>
      <header className="page-header">
        <div>
          <h2>{t("overview.title")}</h2>
          <p>{t("overview.subtitle")}</p>
        </div>
        <a className="button-link" href="http://127.0.0.1:3080" target="_blank" rel="noreferrer">
          {t("overview.openDsh")}
        </a>
      </header>
      <section className="metric-grid" aria-label={t("overview.corpusStatusAria")}>
        <article>
          <span>{t("overview.papers")}</span>
          <strong>{data.sqlite?.paper_count ?? 0}</strong>
        </article>
        <article>
          <span>{t("overview.chunks")}</span>
          <strong>{data.sqlite?.chunk_count ?? 0}</strong>
        </article>
        <article>
          <span>{t("overview.model")}</span>
          <strong>{data.llm?.chat_model ?? t("status.unknown")}</strong>
        </article>
        <article>
          <span>{t("overview.credentials")}</span>
          <StatusBadge tone={credentialsConfigured ? "good" : "warn"}>
            {credentialsConfigured ? t("overview.configured") : t("overview.missing")}
          </StatusBadge>
        </article>
      </section>
      {health ? <HealthSummary data={health} /> : null}
    </>
  );
}
