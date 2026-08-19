import { create } from 'zustand';
import type { StoreState } from './store/types';
import { createDataActions } from './features/data/store';
import { createExecutionActions } from './features/execution/store';
import { createFlowActions } from './features/flow/store';
import { createHistoryActions } from './features/history/store';
import { createPackageActions } from './features/packages/store';
import { createProjectActions } from './features/project/store';

export const useStore = create<StoreState>((set, get) => ({
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
  ...createProjectActions(set, get),
  ...createFlowActions(set, get),
  ...createDataActions(set, get),
  ...createExecutionActions(set, get),
  ...createHistoryActions(set, get),
  ...createPackageActions(set, get),
  clearError: () => set({ error: null }),
}));
