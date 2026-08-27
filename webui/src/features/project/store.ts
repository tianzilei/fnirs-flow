import * as api from '../../api/client';
import type { Project } from '../../api/client';
import type { StoreGet, StoreSet, StoreState } from '../../store/types';
import { restoreExecutionAttempt } from '../execution/store';
import { normalizeFlowPayload } from '../flow/normalization';
import { selectProjectStatus } from './projectStatus';

export const selectProject = (state: StoreState) => state.project;
export const selectProjects = (state: StoreState) => state.projects;
export const selectReadiness = (state: StoreState) => state.readiness;

export function createProjectActions(set: StoreSet, get: StoreGet) {
  return {
    projectStatus: () => selectProjectStatus(get()),

    loadProjects: async (): Promise<void> => {
      try {
        set({ projects: await api.listProjects() });
      } catch (error: unknown) {
        set({ error: { message: 'Failed to load projects', detail: api.formatApiError(error) } });
      }
    },

    createProject: async (name: string, description: string, dataRoot = ''): Promise<Project> => {
      set({ loading: true, error: null });
      try {
        const project = await api.createProject(name, description, dataRoot);
        set((state) => ({
          projects: [...state.projects, project], project, flow: {}, validation: null, compileResult: null,
          discoverResult: null, participantTableResult: null, runs: [], executeInfo: null, currentAttempt: null,
          importStatus: null, readiness: null, progressEvents: [], exportResult: null, snapshot: null, loading: false,
        }));
        return project;
      } catch (error: unknown) {
        set({ error: { message: 'Failed to create project', detail: api.formatApiError(error) }, loading: false });
        throw error;
      }
    },

    selectProject: async (project: Project): Promise<void> => {
      set({
        project, validation: null, compileResult: null, discoverResult: null, participantTableResult: null,
        runs: [], executeInfo: null, currentAttempt: null, importStatus: null, readiness: null,
        progressEvents: [], exportResult: null, snapshot: null, error: null,
      });
      try { set({ flow: normalizeFlowPayload(await api.getFlow(project.id)) }); } catch { set({ flow: {} }); }
      try { set({ importStatus: await api.getImportStatus(project.id) }); } catch { /* optional */ }
      try {
        const readiness = await api.getProjectStatus(project.id);
        set({ readiness });
        if (readiness.compiled) {
          try { set({ compileResult: await api.getCompileResult(project.id) }); } catch { set({ compileResult: null }); }
        }
        if (readiness.data_discovered) {
          try { set({ discoverResult: await api.getDiscoverResult(project.id) }); } catch { set({ discoverResult: null }); }
        }
      } catch { set({ readiness: null }); }
      try {
        await restoreExecutionAttempt(project.id, set);
      } catch { /* older servers may not expose attempts */ }
    },

    refreshStatus: async (): Promise<void> => {
      const { project } = get();
      if (!project) return;
      try { set({ readiness: await api.getProjectStatus(project.id) }); } catch { set({ readiness: null }); }
    },

    loadHealth: async (): Promise<void> => {
      try { set({ healthStatus: await api.getHealth() }); } catch { set({ healthStatus: null }); }
    },
  };
}
