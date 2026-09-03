import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

import { useI18n, type MessageKey } from "../i18n";
import type { QaStreamStage } from "../types";

function StageIcon({ stage }: { stage: QaStreamStage }) {
  if (stage.status === "failed") return <AlertCircle aria-hidden="true" size={16} />;
  if (stage.status === "running") {
    return <Loader2 aria-hidden="true" size={16} className="spin" />;
  }
  return <CheckCircle2 aria-hidden="true" size={16} />;
}

function statusKey(status: string): MessageKey | null {
  if (status === "completed") return "timeline.status.completed";
  if (status === "running") return "timeline.status.running";
  if (status === "failed") return "timeline.status.failed";
  return null;
}

export function AgentTimeline({
  stages,
  running,
}: {
  stages: QaStreamStage[];
  running: boolean;
}) {
  const { t } = useI18n();
  const formatStatus = (status: string) => {
    const key = statusKey(status);
    return key ? t(key) : status;
  };
  if (!running && stages.length === 0) return null;
  return (
    <section className="agent-timeline" aria-label={t("timeline.title")}>
      <header>
        <h3>{t("timeline.title")}</h3>
        {running ? <span className="status-pill degraded">{t("timeline.running")}</span> : null}
      </header>
      <ol>
        {stages.map((stage) => (
          <li key={stage.stage}>
            <StageIcon stage={stage} />
            <div>
              <strong>{stage.label}</strong>
              <span>{formatStatus(stage.status)}</span>
              {typeof stage.elapsed_ms === "number" ? <span>{stage.elapsed_ms} ms</span> : null}
              {stage.summary ? <p>{stage.summary}</p> : null}
              {stage.error ? <p className="error-text">{stage.error}</p> : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
