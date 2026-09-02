import type { StoreGet, StoreSet, StoreState } from '../../store/types';
import * as api from '../../api/client';


export const selectRuns = (state: StoreState) => state.runs;
export const selectExecuteInfo = (state: StoreState) => state.executeInfo;
export const selectCurrentAttempt = (state: StoreState) => state.currentAttempt;
export const selectProgressEvents = (state: StoreState) => state.progressEvents;

const ACTIVE_ATTEMPT_KEY = 'fnirs-flow:active-attempt';

export function rememberActiveAttempt(projectId: string, attemptId: string): void {
  if (typeof localStorage === 'undefined') return;
  localStorage.setItem(ACTIVE_ATTEMPT_KEY, JSON.stringify({ projectId, attemptId }));
}

export function recallActiveAttempt(): { projectId: string; attemptId: string } | null {
  if (typeof localStorage === 'undefined') return null;
  const value = localStorage.getItem(ACTIVE_ATTEMPT_KEY);
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as { projectId?: unknown; attemptId?: unknown };
    if (typeof parsed.projectId !== 'string' || typeof parsed.attemptId !== 'string') return null;
    return { projectId: parsed.projectId, attemptId: parsed.attemptId };
  } catch {
    return null;
  }
}

export function clearActiveAttempt(): void {
  if (typeof localStorage === 'undefined') return;
  localStorage.removeItem(ACTIVE_ATTEMPT_KEY);
}

export function subscribeExecutionProgress(projectId: string, set: StoreSet): () => void {
  return api.subscribeProgress(projectId, (event) => {
    set((state) => ({
      progressEvents: [...state.progressEvents.slice(-50), event],
    }));
  });
}

export async function restoreExecutionAttempt(
  projectId: string,
  set: StoreSet,
  isCurrent: () => boolean = () => true,
): Promise<void> {
  const remembered = recallActiveAttempt();
  const latest = remembered?.projectId === projectId
    ? await api.getExecutionAttempt(projectId, remembered.attemptId)
    : (await api.listExecutionAttempts(projectId))[0];
  if (!latest || !isCurrent()) return;

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
  if (isCurrent() && ['completed', 'failed', 'cancelled'].includes(latest.status)) clearActiveAttempt();
}

export function createExecutionActions(set: StoreSet, get: StoreGet) {
  return {
    subscribeExecutionProgress: (projectId: string): (() => void) =>
      subscribeExecutionProgress(projectId, set),

    dryRun: async (): Promise<void> => {
      const { project } = get();
      if (!project) return;
      set({ loading: true, error: null });
      try {
        const data = await api.dryRun(project.id);
        set({ runs: data.planned_runs || [], dryRunResult: data, executeInfo: null, loading: false });
      } catch (error: unknown) {
        set({ error: { message: 'Dry-run failed', detail: api.formatApiError(error) }, loading: false });
      }
    },

    execute: async (): Promise<void> => {
      const { project } = get();
      if (!project) return;
      set({ loading: true, error: null });
      try {
        let job = await api.executeProject(project.id);
        rememberActiveAttempt(project.id, job.attempt_id);
        set({ currentAttempt: job });
        while (!['completed', 'failed', 'cancelled'].includes(job.status)) {
          await new Promise((resolve) => setTimeout(resolve, 250));
          job = await api.getExecutionAttempt(project.id, job.attempt_id);
          set({ currentAttempt: job });
        }
        if (job.status === 'cancelled') {
          clearActiveAttempt();
          set({ error: { message: 'Execution cancelled' }, loading: false });
          return;
        }
        if (job.status !== 'completed' || !job.result) {
          throw new Error(job.error || `Execution ${job.status}`);
        }
        const data = job.result;
        clearActiveAttempt();
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
      } catch (error: unknown) {
        set({ error: { message: 'Execution failed', detail: api.formatApiError(error) }, loading: false });
      }
    },

    cancelExecution: async (): Promise<void> => {
      const { project, currentAttempt } = get();
      if (!project || !currentAttempt) return;
      try {
        const job = await api.cancelExecutionAttempt(project.id, currentAttempt.attempt_id);
        if (['completed', 'failed', 'cancelled'].includes(job.status)) clearActiveAttempt();
        set({ currentAttempt: job, loading: false });
      } catch (error: unknown) {
        set({ error: { message: 'Cancellation failed', detail: api.formatApiError(error) } });
      }
    },
  };
}
