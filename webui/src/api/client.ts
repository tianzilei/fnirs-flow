import axios from 'axios';
import { normalizeFlowPayload } from '../features/flow/normalization';
import type * as Generated from './generated';

export { createGeneratedApiClient } from './generated';

const API_BASE = '/api';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
});

export function formatApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (detail && typeof detail === 'object') {
      const code = typeof detail.code === 'string' ? `${detail.code}: ` : '';
      const message = typeof detail.message === 'string' ? detail.message : error.message;
      const action = typeof detail.suggested_action === 'string'
        ? ` Suggested action: ${detail.suggested_action}`
        : '';
      return `${code}${message}${action}`;
    }
    if (typeof detail === 'string') return detail;
  }
  return error instanceof Error ? error.message : String(error);
}

export type Project = Omit<Generated.ProjectRead, 'flow_id' | 'package_path' | 'storage_format' | 'revision' | 'integrity_status' | 'integrity_error'> & {
  flow_id: string;
  package_path: string;
  storage_format: string;
  revision: number;
  integrity_status: string;
  integrity_error?: string | null;
};
export type ProjectStatus = Generated.ProjectStatus & {
  flow_saved: boolean; validated: boolean; compiled: boolean; data_discovered: boolean; executed: boolean;
  flow_revision: number; compiled_revision: number; last_attempt_id: string; last_execution_status: string;
};

export async function getProjectStatus(projectId: string): Promise<ProjectStatus> {
  const { data } = await api.get(`/projects/${projectId}/status`);
  return data;
}

export type ValidationResult = Generated.ValidationResult & {
  errors: string[];
  warnings: string[];
  risks: Array<Record<string, unknown>>;
};
export type CompileResult = Omit<Generated.CompileResult, 'dag_layers'> & {
  dag_layers?: Array<Array<{ id: string; atom_type?: string; operation?: string }>>;
};
export type DiscoverResult = Generated.DiscoverResult & {
  source_url: string; metadata_tables: number; processed_hb?: Record<string, unknown>;
};

export type ProjectDataFolder = Generated.FolderEntry;
export type ProjectDataFolderList = Generated.ProjectDataFolderList & {
  parent: string;
  folders: ProjectDataFolder[];
};
export type LocalFolder = Generated.FolderEntry;
export type LocalFolderList = Generated.LocalFolderList & {
  current: string;
  parent: string;
  folders: LocalFolder[];
};
export type DatasetEntry = Required<Generated.DatasetRead>;

export async function listDatasets(): Promise<DatasetEntry[]> {
  const { data } = await api.get('/datasets');
  return data;
}

export async function listProjects(): Promise<Project[]> {
  const { data } = await api.get('/projects');
  return data;
}

export async function getProject(projectId: string): Promise<Project> {
  const { data } = await api.get(`/projects/${projectId}`);
  return data;
}

export async function createProject(name: string, description = '', dataRoot = ''): Promise<Project> {
  const { data } = await api.post('/projects', { name, description, data_root: dataRoot });
  return data;
}

export async function listLocalFolders(path = ''): Promise<LocalFolderList> {
  const { data } = await api.get('/local-folders', {
    params: path ? { path } : {},
  });
  return data;
}

export async function getFlow(projectId: string): Promise<Record<string, unknown>> {
  const { data } = await api.get(`/projects/${projectId}/flow`);
  return data;
}

export async function updateFlow(projectId: string, flow: Record<string, unknown>): Promise<void> {
  await api.put(`/projects/${projectId}/flow`, { flow });
}

export async function validateFlow(projectId: string): Promise<ValidationResult> {
  const { data } = await api.post(`/projects/${projectId}/validate`);
  return data;
}

export async function compileFlow(projectId: string): Promise<CompileResult> {
  const { data } = await api.post(`/projects/${projectId}/compile`);
  return data;
}

export async function getCompileResult(projectId: string): Promise<CompileResult> {
  const { data } = await api.get(`/projects/${projectId}/compile`);
  return data;
}

export async function listProjectDataFolders(projectId: string, parent = ''): Promise<ProjectDataFolderList> {
  const { data } = await api.get(`/projects/${projectId}/data-folders`, {
    params: parent ? { parent } : {},
  });
  return data;
}

export async function discoverData(projectId: string, datasetId: string, dataPath?: string): Promise<DiscoverResult> {
  const { data } = await api.post(`/projects/${projectId}/discover-data`, null, {
    params: { dataset_id: datasetId, ...(dataPath ? { data_path: dataPath } : {}) },
    timeout: 120000,
  });
  return data;
}

export async function getDiscoverResult(projectId: string): Promise<DiscoverResult> {
  const { data } = await api.get(`/projects/${projectId}/discover-data`);
  return data;
}

export type ExampleFlowSummary = Generated.ExampleFlowSummary;

export async function listExampleFlows(): Promise<ExampleFlowSummary[]> {
  const { data } = await api.get('/example-flows');
  return data;
}

export async function getExampleFlow(exampleId: string): Promise<Record<string, unknown>> {
  const { data } = await api.get(`/example-flows/${exampleId}`);
  return data;
}

export type ParticipantTableImportResult = Omit<Generated.ParticipantTableImportResult, 'columns' | 'validation_report'> & {
  columns: Array<{ name: string; inferred_type: string; missing_count: number; unique_count: number; possible_sensitive: boolean }>;
  manifest: Record<string, unknown>;
  column_role_map: Record<string, unknown>;
  validation_report: {
    is_valid: boolean;
    errors: string[];
    warnings: string[];
    join_preview: {
      matched_subjects: string[];
      unmatched_results: string[];
      metadata_without_data: string[];
      duplicate_ids: string[];
      excluded_subjects: string[];
      join_policy: string;
    };
  };
  preview_rows: Array<Record<string, unknown>>;
};

export async function importParticipantTable(
  projectId: string,
  payload: {
    path: string;
    table_kind?: 'participant' | 'observation';
    id_column?: string;
    include_column?: string;
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
    delimiter?: string;
    encoding?: string;
  },
): Promise<ParticipantTableImportResult> {
  const { data } = await api.post(`/projects/${projectId}/participant-table`, payload);
  return data;
}

export type DryRunResult = Generated.DryRunResult & {
  planned_runs: Array<{ run_id: string; status: string; subject: string; session: string; run: string; started_at: string; completed_at: string }>;
  summary: Record<string, unknown>;
};

export async function dryRun(projectId: string): Promise<DryRunResult> {
  const { data } = await api.post(`/projects/${projectId}/dry-run`);
  return data;
}

export type ExecuteResult = Generated.ExecuteResult & {
  attempt_id: string;
  runs: Array<{
    run_id: string;
    status: string;
    subject: string;
    session: string;
    run: string;
    started_at: string;
    completed_at: string;
    atom_results: AtomExecutionSummary[];
    artifacts: ArtifactSummary[];
  }>;
  failure_ids: string[];
};

export type ArtifactSummary = Omit<Generated.ArtifactSummary, 'artifact_id'> & {
  artifact_id: string;
  uri: string;
  path: string;
  resolved_path: string;
  relative_path: string;
  checksum: string;
  exists: boolean;
  atom_id: string;
  step_id: string;
};

export type AtomExecutionSummary = Omit<Generated.AtomResultSummary, 'artifacts' | 'error'> & {
  output_handles: Record<string, unknown>;
  artifacts: ArtifactSummary[];
  warnings: string[];
  error?: string;
};

export type ExecutionJobStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled';

export type ExecutionJob = Omit<Generated.ExecutionJobRead, 'status' | 'result' | 'error'> & {
  status: ExecutionJobStatus;
  started_at: string;
  completed_at: string;
  result?: ExecuteResult;
  error?: string;
};

export async function executeProject(projectId: string): Promise<ExecutionJob> {
  const { data } = await api.post(`/projects/${projectId}/execute`);
  return data;
}

export async function getExecutionAttempt(projectId: string, attemptId: string): Promise<ExecutionJob> {
  const { data } = await api.get(`/projects/${projectId}/attempts/${attemptId}`);
  return data;
}

export async function listExecutionAttempts(projectId: string): Promise<ExecutionJob[]> {
  const { data } = await api.get(`/projects/${projectId}/attempts`);
  return data;
}

export async function cancelExecutionAttempt(projectId: string, attemptId: string): Promise<ExecutionJob> {
  const { data } = await api.post(`/projects/${projectId}/attempts/${attemptId}/cancel`);
  return data;
}

export type ImportStatus = Generated.ImportStatus & { quarantined_atoms: string[] };

export async function getImportStatus(projectId: string): Promise<ImportStatus> {
  const { data } = await api.get(`/projects/${projectId}/import-status`);
  return data;
}

export async function importPackage(projectId: string, packagePath: string): Promise<Record<string, unknown>> {
  const { data } = await api.post(`/projects/${projectId}/import-package`, null, {
    params: { package_path: packagePath },
  });
  return data;
}

export async function forkProject(projectId: string, forkName: string): Promise<Record<string, unknown>> {
  const { data } = await api.post(`/projects/${projectId}/fork`, null, {
    params: { fork_name: forkName },
  });
  return data;
}

export async function trustAtom(projectId: string, atomId: string): Promise<Record<string, unknown>> {
  const { data } = await api.post(`/projects/${projectId}/trust-atom/${atomId}`);
  return data;
}

export async function relinkData(projectId: string, dataRoot: string): Promise<Record<string, unknown>> {
  const { data } = await api.post(`/projects/${projectId}/relink-data`, null, {
    params: { data_root: dataRoot },
  });
  return data;
}

export type ProjectResults = Generated.ProjectResults & { files: Generated.ResultFile[] };

export async function getProjectResults(
  projectId: string,
  kind: ProjectResults['kind'],
): Promise<ProjectResults> {
  const { data } = await api.get(`/projects/${projectId}/results/${kind}`);
  return data;
}

export interface ProgressEvent {
  type: string;
  project_id: string;
  [key: string]: unknown;
}

export function subscribeProgress(
  projectId: string,
  onEvent: (event: ProgressEvent) => void,
): () => void {
  const eventSource = new EventSource(`${API_BASE}/projects/${projectId}/progress`);
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as ProgressEvent;
      onEvent(data);
    } catch {
      // ignore parse errors
    }
  };
  eventSource.onerror = () => {
    // reconnect will happen automatically
  };
  return () => eventSource.close();
}

export type ExportResult = Generated.ExportResult & {
  profile: string;
  contents: string[];
};

export type PackageProfile = Generated.PackageProfile & { include_patterns: string[] };

export async function listPackageProfiles(): Promise<PackageProfile[]> {
  const { data } = await api.get('/package-profiles');
  return data;
}

export interface ExportOptions {
  profile?: string;
  snapshot_id?: string;
  attempt_id?: string;
  include_history?: boolean;
}

export async function exportPackage(projectId: string, options?: ExportOptions): Promise<ExportResult> {
  const { data } = await api.post(`/projects/${projectId}/export-package`, options || {});
  return data;
}

export type AtomTemplate = Generated.AtomTemplate & {
  input_ports: Generated.PortDescription[];
  output_ports: Generated.PortDescription[];
  evidence_refs: string[];
  parameter_options?: Record<string, unknown[]>;
  parameter_specs?: Record<string, Record<string, unknown>>;
  ports?: Array<Generated.PortDescription & { direction: 'in' | 'out' }>;
  origin?: string;
  reference?: string;
  tags?: string[];
  flow_atom_blueprint?: Record<string, unknown>;
};

export async function listAtomTemplates(): Promise<AtomTemplate[]> {
  const { data } = await api.get('/atom-templates');
  return data;
}

export type EmptyMarkerSpec = Generated.EmptyMarkerSpec;

export async function listEmptyMarkerSpecs(): Promise<EmptyMarkerSpec[]> {
  const { data } = await api.get('/empty-marker-specs');
  return data;
}

export type FlowChecklistSummary = Generated.FlowChecklistSummary;
export type FlowChecklistStep = Required<Generated.FlowChecklistStep>;
export type FlowChecklist = Omit<Generated.FlowChecklist, 'steps'> & { steps: FlowChecklistStep[] };

export async function listFlowChecklists(): Promise<FlowChecklistSummary[]> {
  const { data } = await api.get('/flow-checklists');
  return data;
}

export async function getFlowChecklist(scenarioId: string): Promise<FlowChecklist> {
  const { data } = await api.get(`/flow-checklists/${scenarioId}`);
  return data;
}

export type HealthStatus = Generated.HealthStatus;

export async function getHealth(): Promise<HealthStatus> {
  const { data } = await api.get('/health');
  return data;
}

export type BackendDescription = Omit<Generated.BackendDescription, 'description' | 'dependency_profile_id'> & {
  description: string;
  dependency_profile_id?: string;
};

export async function getBackends(): Promise<BackendDescription[]> {
  const { data } = await api.get('/backends');
  return data;
}

export type SnapshotResult = Generated.ProjectSnapshot;

export async function createSnapshot(projectId: string): Promise<SnapshotResult> {
  const { data } = await api.post(`/projects/${projectId}/snapshots`);
  return data;
}

export type VersionHistoryEntry = Generated.VersionHistoryEntry;

export async function getVersionHistory(projectId: string): Promise<VersionHistoryEntry[]> {
  const { data } = await api.get(`/projects/${projectId}/version-history`);
  return data;
}

export async function restoreProjectRevision(projectId: string, revision: number): Promise<Project> {
  const { data } = await api.post(`/projects/${projectId}/bundle/restore/${revision}`);
  return data;
}

// --- Design History (FlowVCS) ---

export type AuthorInfo = Required<Generated.AuthorInfo>;
export type DesignCommitLogEntry = Omit<Generated.CommitLogEntry, 'parents' | 'author'> & {
  parents: string[];
  author: AuthorInfo;
  semantic_flow_hash: string;
  message: string;
  created_at: string;
  reason: string;
};
export type BranchInfo = Generated.BranchInfo & { is_current: boolean };

export type DesignHistoryStatus = Omit<Generated.DesignHistoryStatus, 'head' | 'branches'> & {
  head: DesignCommitLogEntry | null;
  branches: BranchInfo[];
  dirty: boolean;
};

export type DiffChange = Omit<Generated.DiffChange, 'node_id' | 'edge_id' | 'path'> & {
  node_id?: string;
  edge_id?: string;
  path?: string;
};
export type DiffResult = Omit<Generated.DiffResult, 'changes'> & { changes: DiffChange[] };

export async function initializeDesignHistory(projectId: string): Promise<{ commit_id: string }> {
  const { data } = await api.post(`/projects/${projectId}/history/initialize`);
  return data;
}

export async function getDesignHistory(projectId: string): Promise<DesignHistoryStatus> {
  const { data } = await api.get(`/projects/${projectId}/history`);
  return data;
}

export async function listDesignCommits(
  projectId: string,
  branch?: string,
  limit = 50,
  offset = 0,
): Promise<DesignCommitLogEntry[]> {
  const { data } = await api.get(`/projects/${projectId}/history/commits`, {
    params: { branch, limit, offset },
  });
  return data;
}

export async function createDesignCommit(
  projectId: string,
  message: string,
  reason = 'manual_design_commit',
): Promise<{ commit_id: string }> {
  const { data } = await api.post(`/projects/${projectId}/history/commits`, { message, reason });
  return data;
}

export async function getDesignDiff(
  projectId: string,
  fromCommit: string,
  toCommit: string,
): Promise<DiffResult> {
  const { data } = await api.get(`/projects/${projectId}/history/diff`, {
    params: { from_commit: fromCommit, to_commit: toCommit },
  });
  return data;
}

export async function createDesignBranch(
  projectId: string,
  name: string,
  fromCommitId?: string,
): Promise<BranchInfo> {
  const { data } = await api.post(`/projects/${projectId}/history/branches`, {
    name,
    from_commit_id: fromCommitId,
  });
  return data;
}

export async function deleteDesignBranch(projectId: string, name: string): Promise<void> {
  await api.delete(`/projects/${projectId}/history/branches/${name}`);
}

export async function checkoutDesignBranch(
  projectId: string,
  target: string,
): Promise<{ flow: Record<string, unknown>; target: string }> {
  const { data } = await api.post(`/projects/${projectId}/history/checkout`, { target });
  return data;
}

export type MigrationReport = Required<Generated.HistoryMigrationReport>;

export async function migrateDesignHistory(projectId: string): Promise<MigrationReport> {
  const { data } = await api.post(`/projects/${projectId}/history/migrate`);
  return data;
}

// --- AI Draft Review ---

export type AIDraftScenario =
  | 'task'
  | 'resting_state'
  | 'machine_learning'
  | 'real_world'
  | 'hyperscanning'
  | 'multi_site';

export interface AIGenerationMetadata {
  generated_by: string;
  model: string;
  created_at: string;
  input_summary: string;
  assumptions: string[];
  requires_user_confirmation: string[];
  confirmed_parameters: string[];
  confirmed_by: string;
  confirmed_at: string;
  not_used_for_execution: boolean;
  settings?: {
    provider?: string;
    base_url?: string;
    model?: string;
    organization?: string;
    project?: string;
    temperature?: number;
    max_tokens?: number;
    timeout_seconds?: number;
    api_key_present?: boolean;
    mode?: string;
    endpoint?: string;
    direct_import?: boolean;
    provider_status?: string;
    generation_source?: string;
  };
}

export type AIDraftFlow = Generated.AIDraftFlow & Record<string, unknown> & {
  description: string;
  flow_atoms: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  metadata: { ai_generation: AIGenerationMetadata; [key: string]: unknown };
};
export type GenerateAIDraftRequest = Omit<Generated.GenerateAIDraftRequest, 'scenario' | 'ai_settings'> & {
  scenario: AIDraftScenario;
  ai_settings?: Generated.AIDraftSettings & { mode: 'template' | 'openai-compatible' };
};

export interface DraftReadiness {
  status: 'Ready' | 'Needs Attention' | 'Blocked';
  checks: Array<{ name: string; status: 'pass' | 'warn' | 'fail' | 'skip'; message: string }>;
}

export type AIDraftValidation = Omit<Generated.AIDraftValidation, 'status' | 'errors' | 'warnings' | 'risks' | 'readiness'> & {
  status: 'draft_validated'; errors: string[]; warnings: string[];
  risks: Array<{
    risk_id: string;
    code: string;
    severity: string;
    domain: string;
    message: string;
    suggested_action: string;
  }>;
  readiness: DraftReadiness;
};

export async function generateProjectAIDraft(
  projectId: string,
  request: GenerateAIDraftRequest,
): Promise<AIDraftFlow> {
  await api.post(`/projects/${projectId}/ai/draft-flow`, request);
  const draft = await getProjectAIDraft(projectId);
  if (!draft) throw new Error('Draft was generated but could not be loaded');
  return draft;
}

export async function getProjectAIDraft(projectId: string): Promise<AIDraftFlow | null> {
  try {
    const { data } = await api.get(`/projects/${projectId}/ai/draft`);
    return normalizeFlowPayload(data.draft) as AIDraftFlow;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) return null;
    throw error;
  }
}

export async function validateProjectAIDraft(projectId: string): Promise<AIDraftValidation> {
  const { data } = await api.post(`/projects/${projectId}/ai/validate-draft`);
  return data;
}

export async function confirmProjectAIDraft(
  projectId: string,
  confirmedParameters: string[],
  confirmedBy: string,
): Promise<{ status: string; flow_id: string; confirmed_by: string; confirmed_count: number }> {
  const { data } = await api.post(`/projects/${projectId}/ai/confirm-draft`, {
    confirmed_parameters: confirmedParameters,
    confirmed_by: confirmedBy,
  });
  return data;
}

export async function discardProjectAIDraft(projectId: string): Promise<void> {
  await api.delete(`/projects/${projectId}/ai/draft`);
}
