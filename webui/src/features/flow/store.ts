import * as api from '../../api/client';
import type { StoreGet, StoreSet, StoreState } from '../../store/types';
import { normalizeFlowPayload, serializeFlowPayload } from './normalization';

export const selectFlow = (state: StoreState) => state.flow;
export const selectValidation = (state: StoreState) => state.validation;
export const selectCompileResult = (state: StoreState) => state.compileResult;

export function createFlowActions(set: StoreSet, get: StoreGet) {
  return {
    setFlow: (flow: Record<string, unknown>): void => set({
      flow: normalizeFlowPayload(flow), validation: null, compileResult: null, runs: [], executeInfo: null,
      currentAttempt: null, exportResult: null, snapshot: null,
      readiness: get().readiness ? {
        ...get().readiness!, validated: false, compiled: false, executed: false,
        flow_revision: 0, compiled_revision: 0, last_attempt_id: '', last_execution_status: '',
      } : null,
    }),

    saveFlow: async (): Promise<void> => {
      const { project, flow } = get();
      if (!project) return;
      set({ loading: true, error: null });
      try {
        await api.updateFlow(project.id, serializeFlowPayload(flow));
        set({ readiness: await api.getProjectStatus(project.id), loading: false, error: { message: 'Flow saved' } });
      } catch (error: unknown) {
        set({ error: { message: 'Failed to save flow', detail: api.formatApiError(error) }, loading: false });
      }
    },

    validate: async (): Promise<void> => {
      const { project } = get();
      if (!project) return;
      set({ loading: true, error: null });
      try {
        const result = await api.validateFlow(project.id);
        set({
          validation: result, readiness: await api.getProjectStatus(project.id), loading: false,
          error: {
            message: result.is_valid ? 'Validation passed' : 'Validation completed',
            detail: result.is_valid ? 'Flow is ready to compile.' : `${result.errors.length} error(s), ${result.warnings.length} warning(s).`,
          },
        });
      } catch (error: unknown) {
        set({ error: { message: 'Validation failed', detail: api.formatApiError(error) }, loading: false });
      }
    },

    compile: async (): Promise<void> => {
      const { project, flow } = get();
      if (!project) return;
      set({ loading: true, error: null });
      try {
        await api.updateFlow(project.id, serializeFlowPayload(flow));
        const result = await api.compileFlow(project.id);
        set({
          compileResult: result, readiness: await api.getProjectStatus(project.id), loading: false,
          error: { message: 'Compile complete', detail: `${result.steps} step(s), ${result.layers} DAG layer(s).` },
        });
      } catch (error: unknown) {
        set({ error: { message: 'Compilation failed', detail: api.formatApiError(error) }, loading: false });
      }
    },
  };
}
