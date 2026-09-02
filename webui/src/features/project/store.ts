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
  // Project selection performs several independent requests. Keep a generation
  // token so a slow response for the previous project cannot replace state for
  // the project the user selected most recently.
  let selectionGeneration = 0;

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
      const generation = ++selectionGeneration;
      set({ loading: true, error: null });
      try {
        const project = await api.createProject(name, description, dataRoot);
        if (generation === selectionGeneration) {
          set((state) => ({
            projects: [...state.projects, project], project, flow: {}, validation: null, compileResult: null,
            discoverResult: null, participantTableResult: null, runs: [], executeInfo: null, currentAttempt: null,
            importStatus: null, readiness: null, progressEvents: [], exportResult: null, snapshot: null, loading: false,
          }));
        } else {
          set((state) => ({
            projects: state.projects.some((item) => item.id === project.id)
              ? state.projects
              : [...state.projects, project],
          }));
        }
        return project;
      } catch (error: unknown) {
        if (generation === selectionGeneration) {
          set({ error: { message: 'Failed to create project', detail: api.formatApiError(error) }, loading: false });
        }
        throw error;
      }
    },

    selectProject: async (project: Project): Promise<void> => {
      const generation = ++selectionGeneration;
      const isCurrentSelection = () => generation === selectionGeneration;
      set({
        project, validation: null, compileResult: null, discoverResult: null, participantTableResult: null,
        runs: [], executeInfo: null, currentAttempt: null, importStatus: null, readiness: null,
        progressEvents: [], exportResult: null, snapshot: null, error: null,
      });
      try {
        const flow = normalizeFlowPayload(await api.getFlow(project.id));
        if (!isCurrentSelection()) return;
        set({ flow });
      } catch {
        if (!isCurrentSelection()) return;
        set({ flow: {} });
      }
      try {
        const importStatus = await api.getImportStatus(project.id);
        if (!isCurrentSelection()) return;
        set({ importStatus });
      } catch { /* optional */ }
      if (!isCurrentSelection()) return;
      try {
        const readiness = await api.getProjectStatus(project.id);
        if (!isCurrentSelection()) return;
        set({ readiness });
        if (readiness.compiled) {
          try {
            const compileResult = await api.getCompileResult(project.id);
            if (!isCurrentSelection()) return;
            set({ compileResult });
          } catch {
            if (!isCurrentSelection()) return;
            set({ compileResult: null });
          }
        }
        if (readiness.data_discovered) {
          try {
            const discoverResult = await api.getDiscoverResult(project.id);
            if (!isCurrentSelection()) return;
            set({ discoverResult });
          } catch {
            if (!isCurrentSelection()) return;
            set({ discoverResult: null });
          }
        }
      } catch {
        if (!isCurrentSelection()) return;
        set({ readiness: null });
      }
      try {
        await restoreExecutionAttempt(project.id, set, isCurrentSelection);
      } catch { /* older servers may not expose attempts */ }
    },

    refreshStatus: async (): Promise<void> => {
      const { project } = get();
      if (!project) return;
      try {
        const readiness = await api.getProjectStatus(project.id);
        if (get().project?.id === project.id) set({ readiness });
      } catch {
        if (get().project?.id === project.id) set({ readiness: null });
      }
    },

    loadHealth: async (): Promise<void> => {
      try { set({ healthStatus: await api.getHealth() }); } catch { set({ healthStatus: null }); }
    },
  };
}
