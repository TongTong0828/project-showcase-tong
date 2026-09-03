import { useI18n } from "../i18n";

export function CitationChips({
  citations,
  onSelect,
}: {
  citations: string[];
  onSelect?: (citation: string) => void;
}) {
  const { t } = useI18n();
  if (citations.length === 0) {
    return <span className="muted">{t("answer.noCitations")}</span>;
  }

  return (
    <div className="citation-chips" aria-label={t("answer.citationsAria")}>
      {citations.map((citation) => (
        <button key={citation} type="button" onClick={() => onSelect?.(citation)}>
          {citation}
        </button>
      ))}
    </div>
  );
}
