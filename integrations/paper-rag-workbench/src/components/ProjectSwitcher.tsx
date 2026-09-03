import { useState } from "react";

import { useI18n } from "../i18n";
import { useOptionalProjectContext } from "../context/ProjectContext";

export function ProjectSwitcher() {
  const { t } = useI18n();
  const project = useOptionalProjectContext();
  const [name, setName] = useState("");

  if (!project) return null;

  const { projects, activeProjectId, setActiveProjectId, createProject } = project;

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    await createProject(trimmed);
    setName("");
  };

  return (
    <section className="project-switcher" aria-label={t("workspace.projectSwitcher")}>
      <label>
        <span>{t("workspace.selectProject")}</span>
        <select
          value={activeProjectId ?? ""}
          onChange={(event) => setActiveProjectId(event.target.value || null)}
        >
          {projects.map((project) => (
            <option key={project.project_id} value={project.project_id}>
              {project.name}
            </option>
          ))}
        </select>
      </label>
      <form onSubmit={submit}>
        <label>
          <span>{t("workspace.projectName")}</span>
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <button type="submit" disabled={!name.trim()}>
          {t("workspace.createProject")}
        </button>
      </form>
    </section>
  );
}
