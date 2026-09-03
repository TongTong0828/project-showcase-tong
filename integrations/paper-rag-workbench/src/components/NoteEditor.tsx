import { useState } from "react";

import { useI18n } from "../i18n";
import type { NoteInput } from "../types";

export function NoteEditor({
  targetType,
  targetId,
  onSave,
}: {
  targetType: NoteInput["target_type"];
  targetId: string;
  onSave: (input: NoteInput) => Promise<void> | void;
}) {
  const { t } = useI18n();
  const [body, setBody] = useState("");

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = body.trim();
    if (!trimmed) return;
    await onSave({ target_type: targetType, target_id: targetId, body: trimmed });
    setBody("");
  };

  return (
    <form className="note-editor" onSubmit={submit}>
      <label>
        <span>{t("workspace.noteBody")}</span>
        <textarea rows={3} value={body} onChange={(event) => setBody(event.target.value)} />
      </label>
      <button type="submit" disabled={!body.trim()}>
        {t("workspace.saveNote")}
      </button>
    </form>
  );
}
