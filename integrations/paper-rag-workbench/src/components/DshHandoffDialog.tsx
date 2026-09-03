import { useI18n } from "../i18n";
import type { DshHandoffData } from "../types";

export function DshHandoffDialog({
  data,
  onClose,
}: {
  data: DshHandoffData;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const copy = async () => {
    await navigator.clipboard?.writeText(data.prompt);
  };

  return (
    <div className="dialog-backdrop">
      <section className="handoff-dialog" role="dialog" aria-label={t("handoff.title")}>
        <header>
          <h3>{t("handoff.title")}</h3>
          <button type="button" onClick={onClose} aria-label={t("handoff.close")}>
            {t("handoff.closeButton")}
          </button>
        </header>
        <pre>{data.prompt}</pre>
        <footer>
          <button type="button" onClick={copy}>
            {t("handoff.copy")}
          </button>
          <a href={data.dsh_url} target="_blank" rel="noreferrer">
            {t("handoff.open")}
          </a>
        </footer>
      </section>
    </div>
  );
}
