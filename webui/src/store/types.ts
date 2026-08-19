import type * as api from '../api/client';
import type {
  ArtifactSummary,
  AtomExecutionSummary,
  CompileResult,
  DiscoverResult,
  ExecutionJob,
  ExportResult,
  ImportStatus,
  ParticipantTableImportResult,
  ProgressEvent,
  Project,
  ProjectStatus,
  ValidationResult,
} from '../api/client';

export interface ErrorInfo {
  message: string;
  detail?: string;
  status?: number;
}

export interface Run {
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

export interface ExecuteInfo {
  attempt_id: string;
  successful: number;
  failed: number;
  failure_ids: string[];
}

export interface Snapshot {
  snapshot_id: string;
  revision: number;
  created_at: string;
}

export interface ParticipantRoleMapInput {
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

export interface StoreState {
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
  projectStatus: () => {
    selected: boolean;
    flowSaved: boolean;
    validated: boolean;
    compiled: boolean;
    dataDiscovered: boolean;
    executed: boolean;
    hasFatalRisk: boolean;
  };
  loadProjects: () => Promise<void>;
  createProject: (name: string, description: string, dataRoot?: string) => Promise<Project>;
  selectProject: (project: Project) => Promise<void>;
  setFlow: (flow: Record<string, unknown>) => void;
  saveFlow: () => Promise<void>;
  validate: () => Promise<void>;
  compile: () => Promise<void>;
  discover: (datasetId: string, dataPath?: string) => Promise<DiscoverResult>;
  importParticipantTable: (
    path: string,
    idColumn?: string,
    includeColumn?: string,
    roles?: ParticipantRoleMapInput,
  ) => Promise<ParticipantTableImportResult>;
  dryRun: () => Promise<void>;
  execute: () => Promise<void>;
  cancelExecution: () => Promise<void>;
  subscribeExecutionProgress: (projectId: string) => () => void;
  exportPackage: (options?: api.ExportOptions) => Promise<ExportResult>;
  importPackage: (projectId: string, packagePath: string) => Promise<void>;
  createSnapshot: () => Promise<void>;
  fork: () => Promise<Project | null>;
  trustAtom: (atomId: string) => Promise<void>;
  relinkData: (dataRoot: string) => Promise<void>;
  refreshStatus: () => Promise<void>;
  clearError: () => void;
  loadHealth: () => Promise<void>;
}

export type StoreSet = (
  partial: Partial<StoreState> | ((state: StoreState) => Partial<StoreState>),
) => void;
export type StoreGet = () => StoreState;
