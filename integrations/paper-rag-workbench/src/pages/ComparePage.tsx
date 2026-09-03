import { useEffect, useState } from "react";

import { CompareMatrix } from "../components/CompareMatrix";
import { DshHandoffDialog } from "../components/DshHandoffDialog";
import { EmptyState } from "../components/EmptyState";
import { useProjectContext } from "../context/ProjectContext";
import { useI18n, type MessageKey } from "../i18n";
import type { CompareRun, DshHandoffData, WorkbenchClient } from "../types";

const dimensions = [
  { id: "method", labelKey: "compare.method" },
  { id: "limitation", labelKey: "compare.limitation" },
  { id: "contribution", labelKey: "compare.contribution" },
  { id: "dataset", labelKey: "compare.dataset" },
  { id: "experiment", labelKey: "compare.experiment" },
  { id: "evidence_strength", labelKey: "compare.evidenceStrength" },
] as const satisfies readonly { id: string; labelKey: MessageKey }[];

export function ComparePage({ client }: { client: WorkbenchClient }) {
  const { t } = useI18n();
  const { activeProject, activeProjectId, refreshActiveProject } = useProjectContext();
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [selectedPaperIds, setSelectedPaperIds] = useState<string[]>([]);
  const [run, setRun] = useState<CompareRun | null>(null);
  const [handoff, setHandoff] = useState<DshHandoffData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggleDimension = (dimension: string) => {
    setSelectedDimensions((current) =>
      current.includes(dimension)
        ? current.filter((item) => item !== dimension)
        : [...current, dimension],
    );
  };

  useEffect(() => {
    setSelectedPaperIds(activeProject?.papers.map((paper) => paper.paper_id) ?? []);
  }, [activeProject?.project.project_id, activeProject?.papers]);

  const togglePaper = (paperId: string) => {
    setSelectedPaperIds((current) =>
      current.includes(paperId)
        ? current.filter((item) => item !== paperId)
        : [...current, paperId],
    );
  };

  const createCompare = async () => {
    if (!activeProjectId || !activeProject) return;
    setError(null);
    const result = await client.createCompareRun(activeProjectId, {
      paper_ids: selectedPaperIds,
      dimensions: selectedDimensions.length ? selectedDimensions : ["method"],
    });
    setRun(result.run);
    await refreshActiveProject();
  };

  const sendToDsh = async () => {
    if (!activeProjectId || !run) return;
    setHandoff(await client.compareDshHandoff(activeProjectId, run.run_id));
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h2>{t("compare.title")}</h2>
          <p>{t("compare.subtitle")}</p>
        </div>
      </header>
      {!activeProject ? <EmptyState title={t("workspace.noProject")} detail={t("workspace.empty")} /> : null}
      {activeProject ? (
        <section className="panel form-grid">
          <fieldset>
            <legend>{t("compare.dimensions")}</legend>
            <div className="checkbox-grid">
              {dimensions.map((dimension) => (
                <label key={dimension.id}>
                  <input
                    type="checkbox"
                    checked={selectedDimensions.includes(dimension.id)}
                    onChange={() => toggleDimension(dimension.id)}
                  />
                  <span>{t(dimension.labelKey)}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <section>
            <h3>{t("compare.papers")}</h3>
            <div className="checkbox-grid">
              {activeProject.papers.map((paper) => (
                <label key={paper.paper_id}>
                  <input
                    type="checkbox"
                    checked={selectedPaperIds.includes(paper.paper_id)}
                    onChange={() => togglePaper(paper.paper_id)}
                  />
                  <span>{paper.title_snapshot}</span>
                  <code>{paper.paper_id}</code>
                </label>
              ))}
            </div>
          </section>
          <button type="button" onClick={createCompare} disabled={!selectedPaperIds.length}>
            {t("compare.run")}
          </button>
        </section>
      ) : null}
      {error ? <EmptyState title={t("compare.title")} detail={error} /> : null}
      {run ? (
        <>
          <div className="toolbar-row">
            <button type="button" onClick={sendToDsh}>
              {t("compare.sendToDsh")}
            </button>
          </div>
          <CompareMatrix run={run} />
        </>
      ) : null}
      {handoff ? <DshHandoffDialog data={handoff} onClose={() => setHandoff(null)} /> : null}
    </>
  );
}
