import { useState } from "react";

import { useOptionalProjectContext } from "../context/ProjectContext";
import { useI18n } from "../i18n";
import type { EvidenceChunk } from "../types";

export function PinEvidenceButton({
  chunk,
  source = "search",
}: {
  chunk: EvidenceChunk;
  source?: string;
}) {
  const { t } = useI18n();
  const project = useOptionalProjectContext();
  const [saving, setSaving] = useState(false);
  const pinned = Boolean(
    project?.activeProject?.evidence.some((pin) => pin.chunk_id === chunk.chunk_id),
  );

  if (!project?.activeProjectId) return null;

  const pin = async () => {
    setSaving(true);
    await project.addPaper({
      paper_id: chunk.paper_id,
      title_snapshot: chunk.title ?? chunk.paper_title ?? chunk.paper_id,
      source,
    });
    await project.pinEvidence({
      chunk_id: chunk.chunk_id,
      paper_id: chunk.paper_id,
      quote_snapshot: chunk.snippet ?? chunk.text ?? "",
      source,
      score_snapshot: chunk.score,
    });
    setSaving(false);
  };

  return (
    <button
      type="button"
      onClick={pin}
      disabled={pinned || saving}
      aria-label={t("pin.pinEvidenceAria", { id: chunk.chunk_id })}
    >
      {pinned ? t("pin.pinned") : t("pin.pinEvidence")}
    </button>
  );
}
