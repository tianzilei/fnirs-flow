import * as api from '../../api/client';
import type { StoreGet, StoreSet, StoreState } from '../../store/types';

export const selectImportStatus = (state: StoreState) => state.importStatus;
export const selectExportResult = (state: StoreState) => state.exportResult;

export function createPackageActions(set: StoreSet, get: StoreGet) {
  return {
    exportPackage: async (options?: api.ExportOptions) => {
      const { project } = get();
      if (!project) throw new Error('No project selected');
      set({ loading: true, error: null });
      try {
        const result = await api.exportPackage(project.id, options);
        set({ exportResult: result, loading: false });
        return result;
      } catch (error: unknown) {
        set({ error: { message: 'Export failed', detail: api.formatApiError(error) }, loading: false });
        throw error;
      }
    },

    importPackage: async (projectId: string, packagePath: string): Promise<void> => {
      set({ loading: true, error: null });
      try {
        await api.importPackage(projectId, packagePath);
        set({ importStatus: await api.getImportStatus(projectId), loading: false });
      } catch (error: unknown) {
        set({ error: { message: 'Import failed', detail: api.formatApiError(error) }, loading: false });
        throw error;
      }
    },

    fork: async () => {
      const { project } = get();
      if (!project) return null;
      set({ loading: true, error: null });
      try {
        const result = await api.forkProject(project.id, `${project.name}_editable`);
        const newProject = await api.getProject(String(result.fork_project_id));
        set((state) => ({ projects: [...state.projects, newProject], loading: false,
          error: { message: 'Fork created', detail: `New project: ${result.fork_project_id}` } }));
        return newProject;
      } catch (error: unknown) {
        set({ error: { message: 'Fork failed', detail: api.formatApiError(error) }, loading: false });
        return null;
      }
    },

    trustAtom: async (atomId: string): Promise<void> => {
      const { project } = get();
      if (!project) return;
      set({ loading: true, error: null });
      try {
        await api.trustAtom(project.id, atomId);
        const [importStatus, readiness] = await Promise.all([
          api.getImportStatus(project.id),
          api.getProjectStatus(project.id),
        ]);
        set({ importStatus, readiness, loading: false });
      } catch (error: unknown) {
        set({ error: { message: 'Trust failed', detail: api.formatApiError(error) }, loading: false });
      }
    },
  };
}
