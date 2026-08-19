import * as api from '../../api/client';
import type { StoreGet, StoreSet, StoreState } from '../../store/types';

export const selectDiscoverResult = (state: StoreState) => state.discoverResult;
export const selectParticipantTableResult = (state: StoreState) => state.participantTableResult;
export const selectDiscover = (state: StoreState) => state.discover;
export const selectImportParticipantTable = (state: StoreState) => state.importParticipantTable;

export function createDataActions(set: StoreSet, get: StoreGet) {
  return {
    discover: async (datasetId: string, dataPath?: string) => {
      const { project } = get();
      if (!project) throw new Error('No project selected');
      set({ error: null });
      try {
        const result = await api.discoverData(project.id, datasetId, dataPath);
        set({ discoverResult: result, readiness: await api.getProjectStatus(project.id),
          error: { message: 'Dataset discovered', detail: `${result.files} file(s), ${result.runs} run(s).` } });
        return result;
      } catch (error: unknown) {
        set({ error: { message: 'Data discovery failed', detail: api.formatApiError(error) } });
        throw error;
      }
    },

    importParticipantTable: async (path: string, idColumn = 'participant_id', includeColumn = '', roles = {}) => {
      const { project } = get();
      if (!project) throw new Error('No project selected');
      set({ error: null });
      try {
        const result = await api.importParticipantTable(project.id, {
          path, id_column: idColumn, include_column: includeColumn, ...roles,
        });
        set({ participantTableResult: result });
        return result;
      } catch (error: unknown) {
        set({ error: { message: 'Participant table import failed', detail: api.formatApiError(error) } });
        throw error;
      }
    },

    relinkData: async (dataRoot: string): Promise<void> => {
      const { project } = get();
      if (!project) return;
      set({ loading: true, error: null });
      try {
        const relinkResult = await api.relinkData(project.id, dataRoot);
        const [importStatus, readiness] = await Promise.all([
          api.getImportStatus(project.id), api.getProjectStatus(project.id),
        ]);
        set({
          importStatus: { ...importStatus,
            relinked: importStatus.relinked || relinkResult.status === 'relinked',
            data_root: importStatus.data_root || String(relinkResult.data_root || dataRoot) },
          readiness, loading: false,
        });
      } catch (error: unknown) {
        set({ error: { message: 'Relink failed', detail: api.formatApiError(error) }, loading: false });
        throw error;
      }
    },
  };
}
