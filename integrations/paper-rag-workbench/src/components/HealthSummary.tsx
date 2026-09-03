import { useI18n, type MessageKey } from "../i18n";
import type { IndexHealthData } from "../types";
import { DiagnosticCard } from "./DiagnosticCard";
import { WarningBanner } from "./WarningBanner";

function statusKey(status: string): MessageKey | null {
  if (status === "healthy") return "status.healthy";
  if (status === "blocked") return "status.blocked";
  if (status === "fallback") return "status.fallback";
  if (status === "degraded") return "status.degraded";
  return null;
}

export function HealthSummary({ data }: { data: IndexHealthData }) {
  const { t } = useI18n();
  const displayStatus = (status: string) => {
    const key = statusKey(status);
    return key ? t(key) : status;
  };
  return (
    <section className="health-summary">
      <header>
        <h3>{t("health.indexTitle")}</h3>
        <span className={`status-pill ${data.status}`}>{displayStatus(data.status)}</span>
      </header>
      <WarningBanner warnings={data.warnings} />
      <div className="diagnostic-grid">
        <DiagnosticCard
          title="SQLite"
          status={data.sqlite.available ? "healthy" : "blocked"}
          statusLabel={displayStatus(data.sqlite.available ? "healthy" : "blocked")}
        >
          <dl>
            <dt>{t("health.papers")}</dt>
            <dd>{t("health.paperCount", { count: data.sqlite.paper_count })}</dd>
            <dt>{t("health.chunks")}</dt>
            <dd>{t("health.chunkCount", { count: data.sqlite.chunk_count })}</dd>
            <dt>{t("health.fts")}</dt>
            <dd>{data.sqlite.fts_available ? t("status.available") : t("status.unavailable")}</dd>
          </dl>
        </DiagnosticCard>
        <DiagnosticCard
          title="Qdrant"
          status={data.qdrant.reachable ? "healthy" : "fallback"}
          statusLabel={displayStatus(data.qdrant.reachable ? "healthy" : "fallback")}
        >
          <dl>
            <dt>{t("health.mode")}</dt>
            <dd>{data.qdrant.mode}</dd>
            <dt>{t("health.dense")}</dt>
            <dd>{data.retrieval.dense_available ? t("status.available") : t("status.unavailable")}</dd>
            <dt>{t("health.fallback")}</dt>
            <dd>{data.retrieval.sparse_available ? t("status.active") : t("status.unavailable")}</dd>
          </dl>
        </DiagnosticCard>
        <DiagnosticCard
          title="LLM"
          status={data.llm.configured ? "healthy" : "blocked"}
          statusLabel={displayStatus(data.llm.configured ? "healthy" : "blocked")}
        >
          <dl>
            <dt>{t("health.model")}</dt>
            <dd>{data.llm.chat_model}</dd>
            <dt>{t("health.host")}</dt>
            <dd>{data.llm.base_url_host || t("status.notConfigured")}</dd>
            <dt>{t("health.credentials")}</dt>
            <dd>{data.llm.credential_source || t("status.notConfigured")}</dd>
          </dl>
        </DiagnosticCard>
      </div>
    </section>
  );
}
