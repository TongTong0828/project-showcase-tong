import { useState } from "react";

import { DshHandoffDialog } from "../components/DshHandoffDialog";
import { EmptyState } from "../components/EmptyState";
import { NoteEditor } from "../components/NoteEditor";
import { useProjectContext } from "../context/ProjectContext";
import { useI18n } from "../i18n";
import type { DshHandoffData } from "../types";

export function WorkspacePage() {
  const { t } = useI18n();
  const {
    activeProject,
    createProject,
    createNote,
    projectDshHandoff,
    loading,
    error,
  } = useProjectContext();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instruction, setInstruction] = useState("");
  const [handoff, setHandoff] = useState<DshHandoffData | null>(null);

  const submitProject = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    await createProject(trimmed, description.trim());
    setName("");
    setDescription("");
  };

  const sendProjectToDsh = async () => {
    const result = await projectDshHandoff(instruction.trim());
    if (result) setHandoff(result);
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h2>{t("workspace.title")}</h2>
          <p>{t("workspace.subtitle")}</p>
        </div>
      </header>
      <form className="panel form-grid" onSubmit={submitProject}>
        <label>
          <span>{t("workspace.projectName")}</span>
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          <span>{t("workspace.projectDescription")}</span>
          <input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <button type="submit" disabled={!name.trim()}>
          {t("workspace.createProject")}
        </button>
      </form>
      {error ? <EmptyState title={t("workspace.noProject")} detail={error} /> : null}
      {loading && !activeProject ? <p className="loading">{t("workspace.empty")}</p> : null}
      {activeProject ? (
        <section className="workspace-grid">
          <section className="panel project-overview">
            <h3>{activeProject.project.name}</h3>
            {activeProject.project.description ? <p>{activeProject.project.description}</p> : null}
            <div className="metric-grid">
              <span>{t("workspace.paperCount", { count: activeProject.summary.paper_count })}</span>
              <span>
                {t("workspace.evidenceCount", {
                  count: activeProject.summary.evidence_count,
                })}
              </span>
              <span>{t("workspace.noteCount", { count: activeProject.summary.note_count })}</span>
              <span>
                {t("workspace.questionCount", {
                  count: activeProject.summary.saved_question_count,
                })}
              </span>
              <span>
                {t("workspace.compareCount", {
                  count: activeProject.summary.compare_run_count,
                })}
              </span>
            </div>
            <label>
              <span>{t("workspace.dshInstruction")}</span>
              <input
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
              />
            </label>
            <button type="button" onClick={sendProjectToDsh}>
              {t("workspace.sendToDsh")}
            </button>
          </section>
          <section className="panel">
            <h3>{t("workspace.papers")}</h3>
            <ul className="plain-list">
              {activeProject.papers.map((paper) => (
                <li key={paper.paper_id}>
                  <strong>{paper.title_snapshot || paper.paper_id}</strong>
                  <code>{paper.paper_id}</code>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel">
            <h3>{t("workspace.evidence")}</h3>
            <ul className="plain-list">
              {activeProject.evidence.map((pin) => (
                <li key={pin.pin_id}>
                  <code>chunk:{pin.chunk_id}</code>
                  <span>{pin.quote_snapshot}</span>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel">
            <h3>{t("workspace.notes")}</h3>
            <NoteEditor
              targetType="project"
              targetId={activeProject.project.project_id}
              onSave={createNote}
            />
            <ul className="plain-list">
              {activeProject.notes.map((note) => (
                <li key={note.note_id}>
                  <code>
                    {note.target_type}:{note.target_id}
                  </code>
                  <span>{note.body}</span>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel">
            <h3>{t("workspace.savedQuestions")}</h3>
            <ul className="plain-list">
              {activeProject.saved_questions.map((question) => (
                <li key={question.question_id}>
                  <strong>{question.question}</strong>
                  <span>{question.answer}</span>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel">
            <h3>{t("workspace.compareRuns")}</h3>
            <ul className="plain-list">
              {activeProject.compare_runs.map((run) => (
                <li key={run.run_id}>
                  <strong>{run.run_id}</strong>
                  <span>{run.dimensions.join(", ")}</span>
                  <code>{run.status}</code>
                </li>
              ))}
            </ul>
          </section>
        </section>
      ) : null}
      {handoff ? <DshHandoffDialog data={handoff} onClose={() => setHandoff(null)} /> : null}
    </>
  );
}
