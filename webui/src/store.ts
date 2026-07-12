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
  atom_results?: Array<{ atom_id: string; status: string; error?: string }>;
  artifacts?: Array<{ type: string; path: string; checksum: string }>;
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

interface StoreState {
  // Data
  projects: Project[];
  project: Project | null;
  flow: Record<string, unknown>;
  validation: ValidationResult | null;
  compileResult: CompileResult | null;
  discoverResult: DiscoverResult | null;
  runs: Run[];
  executeInfo: ExecuteInfo | null;
  importStatus: ImportStatus | null;
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
  dryRun: () => Promise<void>;
  execute: () => Promise<void>;
  exportPackage: (options?: api.ExportOptions) => Promise<ExportResult>;
  importPackage: (projectId: string, packagePath: string) => Promise<void>;
  createSnapshot: () => Promise<void>;
  fork: () => Promise<void>;
  trustAtom: (atomId: string) => Promise<void>;
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
  runs: [],
  executeInfo: null,
  importStatus: null,
  progressEvents: [],
  exportResult: null,
  snapshot: null,
  loading: false,
  error: null,
  healthStatus: null,

  projectStatus: () => {
    const { project, flow, validation, compileResult, discoverResult, executeInfo } = get();
    const hasFatalRisk = validation?.risks?.some(
      (r: Record<string, unknown>) => r.severity === 'fatal'
    ) ?? false;
    return {
      selected: !!project,
      flowSaved: !!flow && Object.keys(flow).length > 0,
      validated: !!validation,
      compiled: !!compileResult,
      dataDiscovered: !!discoverResult,
      executed: !!executeInfo,
      hasFatalRisk,
    };
  },

  loadProjects: async () => {
    try {
      const projects = await api.listProjects();
      set({ projects });
    } catch (e: any) {
      set({ error: { message: 'Failed to load projects', detail: e.message } });
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
        runs: [],
        executeInfo: null,
        importStatus: null,
        progressEvents: [],
        exportResult: null,
        snapshot: null,
        loading: false,
      }));
      return proj;
    } catch (e: any) {
      set({ error: { message: 'Failed to create project', detail: e.message }, loading: false });
      throw e;
    }
  },

  selectProject: async (project: Project) => {
    set({
      project,
      validation: null,
      compileResult: null,
      discoverResult: null,
      runs: [],
      executeInfo: null,
      importStatus: null,
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
  },

  setFlow: (flow: Record<string, unknown>) => set({ flow }),

  saveFlow: async () => {
    const { project, flow } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      await api.updateFlow(project.id, flow);
      set({ loading: false, error: { message: 'Flow saved', detail: '' } });
    } catch (e: any) {
      set({ error: { message: 'Failed to save flow', detail: e.message }, loading: false });
    }
  },

  validate: async () => {
    const { project } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      const result = await api.validateFlow(project.id);
      set({ validation: result, loading: false });
    } catch (e: any) {
      set({ error: { message: 'Validation failed', detail: e.message }, loading: false });
    }
  },

  compile: async () => {
    const { project, flow } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      await api.updateFlow(project.id, flow);
      const result = await api.compileFlow(project.id);
      set({ compileResult: result, loading: false });
    } catch (e: any) {
      set({ error: { message: 'Compilation failed', detail: e.message }, loading: false });
    }
  },

  discover: async (datasetId: string) => {
    const { project } = get();
    if (!project) throw new Error('No project selected');
    set({ error: null });
    try {
      const result = await api.discoverData(project.id, datasetId);
      set({ discoverResult: result });
      return result;
    } catch (e: any) {
      set({ error: { message: 'Data discovery failed', detail: e.message } });
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
      set({ error: { message: 'Dry-run failed', detail: e.message }, loading: false });
    }
  },

  execute: async () => {
    const { project } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      const data = await api.executeProject(project.id);
      set({
        runs: data.runs || [],
        executeInfo: {
          attempt_id: data.attempt_id,
          successful: data.successful,
          failed: data.failed,
          failure_ids: data.failure_ids,
        },
        loading: false,
      });
    } catch (e: any) {
      set({ error: { message: 'Execution failed', detail: e.message }, loading: false });
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
      set({ error: { message: 'Export failed', detail: e.message }, loading: false });
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
      set({ error: { message: 'Import failed', detail: e.message }, loading: false });
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
      set({ error: { message: 'Snapshot creation failed', detail: e.message }, loading: false });
    }
  },

  fork: async () => {
    const { project } = get();
    if (!project) return;
    set({ loading: true, error: null });
    try {
      const result = await api.forkProject(project.id, `${project.name}_editable`);
      const newProject: Project = {
        id: String(result.fork_project_id),
        name: `${project.name}_editable`,
        description: '',
        flow_id: '',
      };
      set((state) => ({
        projects: [...state.projects, newProject],
        loading: false,
        error: { message: 'Fork created', detail: `New project: ${result.fork_project_id}` },
      }));
    } catch (e: any) {
      set({ error: { message: 'Fork failed', detail: e.message }, loading: false });
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
      set({ error: { message: 'Trust failed', detail: e.message }, loading: false });
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
