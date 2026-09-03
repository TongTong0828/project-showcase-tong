import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type {
  DshHandoffData,
  EvidencePin,
  EvidencePinInput,
  NoteInput,
  ProjectDetail,
  ProjectPaper,
  ProjectPaperInput,
  ProjectSummary,
  SavedQuestion,
  SavedQuestionInput,
  WorkbenchClient,
} from "../types";

type ProjectContextValue = {
  projects: ProjectSummary[];
  activeProjectId: string | null;
  activeProject: ProjectDetail | null;
  loading: boolean;
  error: string | null;
  setActiveProjectId: (projectId: string | null) => void;
  refreshProjects: () => Promise<void>;
  refreshActiveProject: () => Promise<void>;
  createProject: (name: string, description?: string) => Promise<ProjectSummary>;
  addPaper: (input: ProjectPaperInput) => Promise<ProjectPaper | null>;
  pinEvidence: (input: EvidencePinInput) => Promise<EvidencePin | null>;
  createNote: (input: NoteInput) => Promise<void>;
  saveQuestion: (input: SavedQuestionInput) => Promise<SavedQuestion | null>;
  projectDshHandoff: (instruction?: string) => Promise<DshHandoffData | null>;
};

const ProjectContext = createContext<ProjectContextValue | null>(null);

export function ProjectProvider({
  client,
  children,
}: {
  client: WorkbenchClient;
  children: ReactNode;
}) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProjectId, setActiveProjectIdState] = useState<string | null>(null);
  const activeProjectIdRef = useRef<string | null>(null);
  const [activeProject, setActiveProject] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshProjects = useCallback(async () => {
    setError(null);
    const result = await client.projects();
    setProjects(result.projects);
    const currentId = activeProjectIdRef.current;
    const currentExists = result.projects.some((project) => project.project_id === currentId);
    const nextProjectId = currentExists ? currentId : result.projects[0]?.project_id ?? null;
    activeProjectIdRef.current = nextProjectId;
    setActiveProjectIdState(nextProjectId);
    if (!nextProjectId) {
      setActiveProject(null);
      return;
    }
    setActiveProject(await client.project(nextProjectId));
  }, [client]);

  const refreshActiveProject = useCallback(async () => {
    if (!activeProjectId) {
      setActiveProject(null);
      return;
    }
    setError(null);
    setActiveProject(await client.project(activeProjectId));
  }, [activeProjectId, client]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    refreshProjects()
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [refreshProjects]);

  useEffect(() => {
    let active = true;
    refreshActiveProject().catch((reason: unknown) => {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => {
      active = false;
    };
  }, [refreshActiveProject]);

  const setActiveProjectId = useCallback((projectId: string | null) => {
    activeProjectIdRef.current = projectId;
    setActiveProjectIdState(projectId);
  }, []);

  const createProject = useCallback(
    async (name: string, description = "") => {
      const result = await client.createProject({ name, description });
      await refreshProjects();
      activeProjectIdRef.current = result.project.project_id;
      setActiveProjectIdState(result.project.project_id);
      setActiveProject(await client.project(result.project.project_id));
      return result.project;
    },
    [client, refreshProjects],
  );

  const resolvedProjectSummary =
    projects.find((project) => project.project_id === activeProjectId) ?? projects[0] ?? null;
  const resolvedActiveProjectId = activeProjectId ?? resolvedProjectSummary?.project_id ?? null;
  const fallbackActiveProject = resolvedProjectSummary
    ? {
        project: resolvedProjectSummary,
        summary: {
          paper_count: 0,
          evidence_count: 0,
          note_count: 0,
          saved_question_count: 0,
          compare_run_count: 0,
        },
        papers: [],
        evidence: [],
        notes: [],
        saved_questions: [],
        compare_runs: [],
        warnings: [],
      }
    : null;
  const resolvedActiveProject = activeProject ?? fallbackActiveProject;

  const requireActiveId = useCallback(
    () => resolvedActiveProjectId,
    [resolvedActiveProjectId],
  );

  const addPaper = useCallback(
    async (input: ProjectPaperInput) => {
      const projectId = requireActiveId();
      if (!projectId) return null;
      const result = await client.addProjectPaper(projectId, input);
      setActiveProject(await client.project(projectId));
      await refreshProjects();
      return result.paper;
    },
    [client, refreshProjects, requireActiveId],
  );

  const pinEvidence = useCallback(
    async (input: EvidencePinInput) => {
      const projectId = requireActiveId();
      if (!projectId) return null;
      const result = await client.pinEvidence(projectId, input);
      setActiveProject(await client.project(projectId));
      await refreshProjects();
      return result.evidence;
    },
    [client, refreshProjects, requireActiveId],
  );

  const createNote = useCallback(
    async (input: NoteInput) => {
      const projectId = requireActiveId();
      if (!projectId) return;
      await client.createNote(projectId, input);
      setActiveProject(await client.project(projectId));
      await refreshProjects();
    },
    [client, refreshProjects, requireActiveId],
  );

  const saveQuestion = useCallback(
    async (input: SavedQuestionInput) => {
      const projectId = requireActiveId();
      if (!projectId) return null;
      const result = await client.saveQuestion(projectId, input);
      setActiveProject(await client.project(projectId));
      await refreshProjects();
      return result.question;
    },
    [client, refreshProjects, requireActiveId],
  );

  const projectDshHandoff = useCallback(
    async (instruction = "") => {
      const projectId = requireActiveId();
      if (!projectId) return null;
      return client.projectDshHandoff(projectId, { instruction });
    },
    [client, requireActiveId],
  );

  const value = useMemo<ProjectContextValue>(
    () => ({
      projects,
      activeProjectId: resolvedActiveProjectId,
      activeProject: resolvedActiveProject,
      loading,
      error,
      setActiveProjectId,
      refreshProjects,
      refreshActiveProject,
      createProject,
      addPaper,
      pinEvidence,
      createNote,
      saveQuestion,
      projectDshHandoff,
    }),
    [
      activeProject,
      activeProjectId,
      addPaper,
      createNote,
      createProject,
      error,
      loading,
      pinEvidence,
      projectDshHandoff,
      projects,
      refreshActiveProject,
      refreshProjects,
      resolvedActiveProject,
      resolvedActiveProjectId,
      saveQuestion,
      setActiveProjectId,
    ],
  );

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProjectContext(): ProjectContextValue {
  const value = useContext(ProjectContext);
  if (!value) {
    throw new Error("useProjectContext must be used inside ProjectProvider");
  }
  return value;
}

export function useOptionalProjectContext(): ProjectContextValue | null {
  return useContext(ProjectContext);
}
