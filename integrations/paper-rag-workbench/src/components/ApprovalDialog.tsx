import type { MessageKey } from "../i18n";
import { useI18n } from "../i18n";

const SIDE_EFFECTS = [
  "write indexed paper and chunks",
  "update the configured Paper RAG corpus",
  "record ingestion metadata",
];

const SIDE_EFFECT_KEYS = [
  "approval.effect.write",
  "approval.effect.update",
  "approval.effect.record",
] as const satisfies readonly MessageKey[];

export function ApprovalDialog({
  open,
  candidateIds,
  onCancel,
  onApprove,
}: {
  open: boolean;
  candidateIds: number[];
  onCancel: () => void;
  onApprove: () => void;
}) {
  const { t } = useI18n();
  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-label={t("approval.aria")}>
        <h3>{t("approval.title")}</h3>
        <p>{t("approval.candidateIds", { ids: candidateIds.join(", ") })}</p>
        <ul>
          {SIDE_EFFECT_KEYS.map((effectKey) => (
            <li key={effectKey}>{t(effectKey)}</li>
          ))}
        </ul>
        <div className="row-actions">
          <button type="button" onClick={onCancel}>
            {t("approval.cancel")}
          </button>
          <button type="button" className="primary" onClick={onApprove}>
            {t("approval.approve")}
          </button>
        </div>
      </section>
    </div>
  );
}

export const candidateIngestSideEffects = SIDE_EFFECTS;
