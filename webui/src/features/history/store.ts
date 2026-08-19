import * as api from '../../api/client';
import type { StoreGet, StoreSet, StoreState } from '../../store/types';

export const selectSnapshot = (state: StoreState) => state.snapshot;

export function createHistoryActions(set: StoreSet, get: StoreGet) {
  return {
    createSnapshot: async (): Promise<void> => {
      const { project } = get();
      if (!project) return;
      set({ loading: true, error: null });
      try { set({ snapshot: await api.createSnapshot(project.id), loading: false }); }
      catch (error: unknown) {
        set({ error: { message: 'Snapshot creation failed', detail: api.formatApiError(error) }, loading: false });
      }
    },
  };
}
