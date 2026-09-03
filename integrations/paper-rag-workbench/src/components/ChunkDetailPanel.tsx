import { useI18n } from "../i18n";
import type { ChunkDetailData } from "../types";
import { ScoreBreakdown } from "./ScoreBreakdown";

export function ChunkDetailPanel({
  detail,
  onOpenPaper,
}: {
  detail: ChunkDetailData;
  onOpenPaper: (paperId: string) => void;
}) {
  const { t } = useI18n();
  const warnings = detail.chunk.warnings || [];
  return (
    <aside className="chunk-detail panel" aria-label={t("chunkDetail.aria")}>
      <header>
        <div>
          <h3>{detail.paper.title || detail.chunk.paper_id}</h3>
          <code>chunk:{detail.chunk.chunk_id}</code>
        </div>
        <button type="button" onClick={() => onOpenPaper(detail.chunk.paper_id)}>
          {t("chunkDetail.openPaper")}
        </button>
      </header>
      <dl className="metadata-grid">
        <dt>{t("chunkDetail.paper")}</dt>
        <dd>{detail.chunk.paper_id}</dd>
        <dt>{t("chunkDetail.section")}</dt>
        <dd>{detail.chunk.section || t("chunkDetail.unknown")}</dd>
        <dt>{t("chunkDetail.page")}</dt>
        <dd>{detail.chunk.page || t("chunkDetail.unknown")}</dd>
      </dl>
      <ScoreBreakdown chunk={detail.chunk} />
      {warnings.length ? (
        <div className="inline-warnings">
          {warnings.map((warning) => (
            <span key={warning}>{warning}</span>
          ))}
        </div>
      ) : null}
      <p className="chunk-full-text">{detail.chunk.text || detail.chunk.snippet}</p>
      {detail.neighbors.length ? (
        <section>
          <h4>{t("chunkDetail.nearby")}</h4>
          {detail.neighbors.map((neighbor) => (
            <article key={neighbor.chunk_id}>
              <code>chunk:{neighbor.chunk_id}</code>
              <p>{neighbor.text || neighbor.snippet}</p>
            </article>
          ))}
        </section>
      ) : null}
    </aside>
  );
}
