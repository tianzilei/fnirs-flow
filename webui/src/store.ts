import { create } from 'zustand';
import * as api from './api/client';
import type {
  Project,
  ValidationResult,
  CompileResult,
  DiscoverResult,
  ExportResult,
  ProgressEvent,
  ImportStatus,
  ProjectStatus,
  ExecutionJob,
  ArtifactSummary,
  AtomExecutionSummary,
  ParticipantTableImportResult,
} from './api/client';

interface ErrorInfo {
  message: string;
  detail?: string;
  status?: number;
}

interface Run {
  run_id: string;
  status: string;
  subject: string;
  session: string;
  run: string;
  started_at: string;
  completed_at: string;
  atom_results?: AtomExecutionSummary[];
  artifacts?: ArtifactSummary[];
}

interface ExecuteInfo {
  attempt_id: string;
  successful: number;
  failed: number;
  failure_ids: string[];
}

interface Snapshot {
  snapshot_id: string;
  flow_hash: string;
  created_at: string;
}

interface ParticipantRoleMapInput {
  group_column?: string;
  label_column?: string;
  site_column?: string;
  scanner_column?: string;
  covariate_columns?: string[];
  session_column?: string;
  timepoint_column?: string;
  pair_id_column?: string;
  dyad_id_column?: string;
  participant_role_column?: string;
}

interface StoreState {
  // Data
  projects: Project[];
  project: Project | null;
  flow: Record<string, unknown>;
  validation: ValidationResult | null;
  compileResult: CompileResult | null;
  discoverResult: DiscoverResult | null;
  participantTableResult: ParticipantTableImportResult | null;
  runs: Run[];
  executeInfo: ExecuteInfo | null;
  currentAttempt: ExecutionJob | null;
  importStatus: ImportStatus | null;
  readiness: ProjectStatus | null;
  progressEvents: ProgressEvent[];
  exportResult: ExportResult | null;
  snapshot: Snapshot | null;
  loading: boolean;
  error: ErrorInfo | null;
  healthStatus: { status: string; version: string } | null;

  // Computed-like
  projectStatus: () => {
    selected: boolean;
    flowSaved: boolean;
    validated: boolean;
    compiled: boolean;
    dataDiscovered: boolean;
    executed: boolean;
    hasFatalRisk: boolean;
  };

  // Actions
  loadProjects: () => Promise<void>;
  createProject: (name: string, description: string) => Promise<Project>;
  selectProject: (project: Project) => Promise<void>;
  setFlow: (flow: Record<string, unknown>) => void;
  saveFlow: () => Promise<void>;
  validate: () => Promise<void>;
  compile: () => Promise<void>;
  discover: (datasetId: string) => Promise<DiscoverResult>;
  importParticipantTable: (
    path: string,
    idColumn?: string,
    includeColumn?: string,
    roles?: ParticipantRoleMapInput,
  ) => Promise<ParticipantTableImportResult>;
  dryRun: () => Promise<void>;
  execute: () => Promise<void>;
  cancelExecution: () => Promise<void>;
  exportPackage: (options?: api.ExportOptions) => Promise<ExportResult>;
  importPackage: (projectId: string, packagePath: string) => Promise<void>;
  createSnapshot: () => Promise<void>;
  fork: () => Promise<void>;
  trustAtom: (atomId: string) => Promise<void>;
  relinkData: (dataRoot: string) => Promise<void>;
  refreshStatus: () => Promise<void>;
  clearError: () => void;
  loadHealth: () => Promise<void>;
}

export const useStore = create<StoreState>((set, get) => ({
  // Initial state
  projects: [],
  project: null,
  flow: {},
  validation: null,
  compileResult: null,
  discoverResult: null,
  participantTableResult: null,
  runs: [],
  executeInfo: null,
  currentAttempt: null,
  importStatus: null,
  readiness: null,
  progressEvents: [],
  exportResult: null,
  snapshot: null,
  loading: false,
  error: null,
  healthStatus: null,

  projectStatus: () => {
    const { project, flow, validation, compileResult, discoverResult, executeInfo, readiness } = get();
    const hasFatalRisk = validation?.risks?.some(
      (r: Record<string, unknown>) => r.severity === 'fatal'
    ) ?? false;
    const validationPassed = validation ? validation.is_valid && !hasFatalRisk : !!readiness?.validated;
    return {
      selected: !!project,
      flowSaved: (!!flow && Object.keys(flow).length > 0) || !!readiness?.flow_saved,
      validated: validationPassed,
      compiled: !!compileResult || !!readiness?.compiled,
      dataDiscovered: !!discoverResult || !!readiness?.data_discovered,
      executed: !!executeInfo || !!readiness?.executed,
      hasFatalRisk,
    };
  },

  loadProjects: async () => {
    try {
      const projects = await api.listProjects();
      set({ projects });
    } catch (e: any) {
      set({ error: { message: 'Failed to load projects', detail: api.formatApiError(e) } });
    }
  },

  createProject: async (name: string, description: string) => {
    set({ loading: true, error: null });
    try {
      const proj = await api.createProject(name, description);
      set((state) => ({
        projects: [...state.projects, proj],
        project: proj,
        flow: {},
        validation: null,
        compileResult: null,
        discoverResult: null,
        participantTableResult: null,
        runs: [],
        executeInfo: null,
        currentAttempt: null,
        importStatus: null,
        readiness: null,
        progressEvents: [],
        exportResult: null,
        snapshot: null,
        loading: false,
      }));
      return proj;
    } catch (e: any) {
      set({ error: { message: 'Failed to create project', detail: api.formatApiError(e) }, loading: false });
      throw e;
    }
  },

  selectProject: async (project: Project) => {
    set({
      project,
      validation: null,
      compileResult: null,
      discoverResult: null,
      participantTableResult: null,
      runs: [],
      executeInfo: null,
      currentAttempt: null,
      importStatus: null,
      readiness: null,
      progressEvents: [],
      exportResult: null,
      snapshot: null,
      error: null,
    });
    try {
      const flowData = await api.getFlow(project.id);
      set({ flow: flowData });
    } catch {
      set({ flow: {} });
    }
    try {
      const status = await api.getImportStatus(project.id);
      set({ importStatus: status });
    } catch {
      // ignore
    }
    try {
      const readiness = await api.getProjectStatus(project.id);
      set({ readiness });
    } catch {
      set({ readiness: null });
    }
    try {
      const [latest] = await api.listExecutionAttempts(project.id);
      if (latest) {
        const result = latest.result;
        set({
          currentAttempt: latest,
          runs: result?.runs || [],
          executeInfo: result ? {
            attempt_id: result.attempt_id,
            successful: result.successful,
            failed: result.failed,
            failure_ids: result.failure_ids,
          } : null,
        });
      }
    } catch {
      // Older servers may not expose persistent attempts.
    }
  },

  setFlow: (flow: Record<string, unknown>) => set({
    flow,
    validation: null,
    compileResult: null,
    runs: [],
    executeInfo: null,
    currentAttempt: null,
    exportResult: null,
    snapshot: null,
    readiness: get().readiness ? {
      ...get().readiness!,
      validated: false,
      compiled: false,
      executed: false,
      flow_hash: '',
      compiled_flow_hash: '',
      last_attempt_id: '',
      last_execution_status: '',
    } : null,
  }),

  saveFlow: async () => {
    const { project, flow } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      await api.updateFlow(project.id, flow);
      const readiness = await api.getProjectStatus(project.id);
      set({ readiness, loading: false, error: { message: 'Flow saved' } });
    } catch (e: any) {
      set({ error: { message: 'Failed to save flow', detail: api.formatApiError(e) }, loading: false });
    }
  },

  validate: async () => {
    const { project } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      const result = await api.validateFlow(project.id);
      const readiness = await api.getProjectStatus(project.id);
      set({ validation: result, readiness, loading: false });
    } catch (e: any) {
      set({ error: { message: 'Validation failed', detail: api.formatApiError(e) }, loading: false });
    }
  },

  compile: async () => {
    const { project, flow } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      await api.updateFlow(project.id, flow);
      const result = await api.compileFlow(project.id);
      const readiness = await api.getProjectStatus(project.id);
      set({ compileResult: result, readiness, loading: false });
    } catch (e: any) {
      set({ error: { message: 'Compilation failed', detail: api.formatApiError(e) }, loading: false });
    }
  },

  discover: async (datasetId: string) => {
    const { project } = get();
    if (!project) throw new Error('No project selected');
    set({ error: null });
    try {
      const result = await api.discoverData(project.id, datasetId);
      const readiness = await api.getProjectStatus(project.id);
      set({ discoverResult: result, readiness });
      return result;
    } catch (e: any) {
      set({ error: { message: 'Data discovery failed', detail: api.formatApiError(e) } });
      throw e;
    }
  },

  importParticipantTable: async (path: string, idColumn = 'participant_id', includeColumn = 'include', roles = {}) => {
    const { project } = get();
    if (!project) throw new Error('No project selected');
    set({ error: null });
    try {
      const result = await api.importParticipantTable(project.id, {
        path,
        id_column: idColumn,
        include_column: includeColumn,
        ...roles,
      });
      set({ participantTableResult: result });
      return result;
    } catch (e: any) {
      set({ error: { message: 'Participant table import failed', detail: api.formatApiError(e) } });
      throw e;
    }
  },

  dryRun: async () => {
    const { project } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      const data = await api.dryRun(project.id);
      set({ runs: data.planned_runs || [], executeInfo: null, loading: false });
    } catch (e: any) {
      set({ error: { message: 'Dry-run failed', detail: api.formatApiError(e) }, loading: false });
    }
  },

  execute: async () => {
    const { project } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      let job = await api.executeProject(project.id);
      set({ currentAttempt: job });
      while (!['completed', 'failed', 'cancelled'].includes(job.status)) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        job = await api.getExecutionAttempt(project.id, job.attempt_id);
        set({ currentAttempt: job });
      }
      if (job.status === 'cancelled') {
        set({ error: { message: 'Execution cancelled' }, loading: false });
        return;
      }
      if (job.status !== 'completed' || !job.result) {
        throw new Error(job.error || `Execution ${job.status}`);
      }
      const data = job.result;
      const readiness = await api.getProjectStatus(project.id);
      set({
        runs: data.runs || [],
        executeInfo: {
          attempt_id: data.attempt_id,
          successful: data.successful,
          failed: data.failed,
          failure_ids: data.failure_ids,
        },
        readiness,
        loading: false,
      });
    } catch (e: any) {
      set({ error: { message: 'Execution failed', detail: api.formatApiError(e) }, loading: false });
    }
  },

  cancelExecution: async () => {
    const { project, currentAttempt } = get();
    if (!project || !currentAttempt) return;
    try {
      const job = await api.cancelExecutionAttempt(project.id, currentAttempt.attempt_id);
      set({ currentAttempt: job, loading: false });
    } catch (e: any) {
      set({ error: { message: 'Cancellation failed', detail: api.formatApiError(e) } });
    }
  },

  exportPackage: async (options?: api.ExportOptions) => {
    const { project } = get();
    if (!project) throw new Error('No project selected');
    set({ loading: true, error: null });
    try {
      const result = await api.exportPackage(project.id, options);
      set({ exportResult: result, loading: false });
      return result;
    } catch (e: any) {
      set({ error: { message: 'Export failed', detail: api.formatApiError(e) }, loading: false });
      throw e;
    }
  },

  importPackage: async (projectId: string, packagePath: string) => {
    set({ loading: true, error: null });
    try {
      await api.importPackage(projectId, packagePath);
      const status = await api.getImportStatus(projectId);
      set({ importStatus: status, loading: false });
    } catch (e: any) {
      set({ error: { message: 'Import failed', detail: api.formatApiError(e) }, loading: false });
      throw e;
    }
  },

  createSnapshot: async () => {
    const { project } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      const result = await api.createSnapshot(project.id);
      set({ snapshot: result, loading: false });
    } catch (e: any) {
      set({ error: { message: 'Snapshot creation failed', detail: api.formatApiError(e) }, loading: false });
    }
  },

  fork: async () => {
    const { project } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      const result = await api.forkProject(project.id, `${project.name}_editable`);
      const newProject = await api.getProject(String(result.fork_project_id));
      set((state) => ({
        projects: [...state.projects, newProject],
        loading: false,
        error: { message: 'Fork created', detail: `New project: ${result.fork_project_id}` },
      }));
    } catch (e: any) {
      set({ error: { message: 'Fork failed', detail: api.formatApiError(e) }, loading: false });
    }
  },

  trustAtom: async (atomId: string) => {
    const { project } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      await api.trustAtom(project.id, atomId);
      const status = await api.getImportStatus(project.id);
      set({ importStatus: status, loading: false });
    } catch (e: any) {
      set({ error: { message: 'Trust failed', detail: api.formatApiError(e) }, loading: false });
    }
  },

  relinkData: async (dataRoot: string) => {
    const { project } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      await api.relinkData(project.id, dataRoot);
      const [importStatus, readiness] = await Promise.all([
        api.getImportStatus(project.id),
        api.getProjectStatus(project.id),
      ]);
      set({ importStatus, readiness, loading: false });
    } catch (e: any) {
      set({ error: { message: 'Relink failed', detail: api.formatApiError(e) }, loading: false });
      throw e;
    }
  },

  refreshStatus: async () => {
    const { project } = get();
    if (!project) return;
    try {
      const readiness = await api.getProjectStatus(project.id);
      set({ readiness });
    } catch {
      set({ readiness: null });
    }
  },

  clearError: () => set({ error: null }),

  loadHealth: async () => {
    try {
      const data = await api.getHealth();
      set({ healthStatus: data });
    } catch {
      set({ healthStatus: null });
    }
  },
}));
