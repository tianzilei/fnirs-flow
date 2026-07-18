import axios from 'axios';

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

export interface Project {
  id: string;
  name: string;
  description: string;
  flow_id: string;
  package_path: string;
  storage_format: 'fnirsflow_bundle';
  revision: number;
  integrity_status: 'unknown' | 'verified' | 'failed';
  last_verified_at?: string | null;
  integrity_error?: string | null;
}

export interface ProjectStatus {
  flow_saved: boolean;
  validated: boolean;
  compiled: boolean;
  data_discovered: boolean;
  runnable_runs: number;
  executed: boolean;
  flow_hash: string;
  compiled_flow_hash: string;
  last_attempt_id: string;
  last_execution_status: string;
  read_only: boolean;
  quarantined_atoms: string[];
}

export async function getProjectStatus(projectId: string): Promise<ProjectStatus> {
  const { data } = await api.get(`/projects/${projectId}/status`);
  return data;
}

export interface ValidationResult {
  is_valid: boolean;
  errors: string[];
  warnings: string[];
  risks: Record<string, unknown>[];
}

export interface CompileResult {
  flow_id: string;
  flow_hash: string;
  steps: number;
  layers: number;
  output_files: string[];
  dag_layers?: Array<Array<{
    id: string;
    atom_type?: string;
    node_type?: string;
    operation?: string;
  }>>;
}

export interface DiscoverResult {
  dataset_id: string;
  files: number;
  runs: number;
  local_root: string;
  source_url: string;
  metadata_tables: number;
}

export interface DatasetEntry {
  dataset_id: string;
  name: string;
  source_kind: string;
  url: string;
  doi: string;
  citation: string;
  license: string;
  description: string;
  folder_name: string;
}

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

export async function createProject(name: string, description = ''): Promise<Project> {
  const { data } = await api.post('/projects', { name, description });
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

export async function discoverData(projectId: string, datasetId: string): Promise<DiscoverResult> {
  const { data } = await api.post(`/projects/${projectId}/discover-data`, null, {
    params: { dataset_id: datasetId },
    timeout: 120000,
  });
  return data;
}

export interface ParticipantTableImportResult {
  table_kind: string;
  rows: number;
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
}

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

export interface DryRunResult {
  total_runs: number;
  planned_runs: Array<{ run_id: string; status: string; subject: string; session: string; run: string; started_at: string; completed_at: string }>;
  summary: Record<string, unknown>;
}

export async function dryRun(projectId: string): Promise<DryRunResult> {
  const { data } = await api.post(`/projects/${projectId}/dry-run`);
  return data;
}

export interface ExecuteResult {
  attempt_id: string;
  total_runs: number;
  successful: number;
  failed: number;
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
}

export interface ArtifactSummary {
  artifact_id: string;
  type: string;
  uri: string;
  path: string;
  resolved_path: string;
  relative_path: string;
  checksum: string;
  exists: boolean;
  atom_id: string;
  step_id: string;
}

export interface AtomExecutionSummary {
  atom_id: string;
  status: string;
  output_handles: Record<string, unknown>;
  artifacts: ArtifactSummary[];
  warnings: string[];
  error?: string;
}

export type ExecutionJobStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled';

export interface ExecutionJob {
  attempt_id: string;
  project_id: string;
  status: ExecutionJobStatus;
  created_at: string;
  started_at: string;
  completed_at: string;
  recovery_count: number;
  cancel_requested: boolean;
  result?: ExecuteResult;
  error?: string;
}

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

export interface ImportStatus {
  imported: boolean;
  read_only: boolean;
  quarantined_atoms: string[];
  relinked?: boolean;
  data_root?: string;
}

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

export interface ProjectResults {
  kind: 'qc' | 'channel' | 'roi' | 'group';
  file_count: number;
  files: Array<{ path: string; data: unknown }>;
  figures?: Array<{ path: string; svg: string }>;
}

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

export interface ExportResult {
  package_path: string;
  size_bytes: number;
  profile: string;
  contents: string[];
}

export interface PackageProfile {
  profile_id: string;
  name: string;
  description: string;
  include_patterns: string[];
}

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

export interface AtomTemplate {
  id: string;
  atom_type: string;
  display_name: string;
  category: string;
  operation: string;
  description: string;
  input_ports: Array<{ name: string; schema: string; required: boolean }>;
  output_ports: Array<{ name: string; schema: string; required: boolean }>;
  ports?: Array<{ name: string; direction: 'in' | 'out'; schema: string; required: boolean }>;
  evidence_refs: string[];
}

export async function listAtomTemplates(): Promise<AtomTemplate[]> {
  const { data } = await api.get('/atom-templates');
  return data;
}

export interface EmptyMarkerSpec {
  category: string;
  input_schema: string;
  output_schema: string;
  label: string;
  atom_id: string;
  template_id: string;
}

export async function listEmptyMarkerSpecs(): Promise<EmptyMarkerSpec[]> {
  const { data } = await api.get('/empty-marker-specs');
  return data;
}

export interface FlowChecklistSummary {
  scenario_id: string;
  label: string;
  description: string;
  version: string;
  step_count: number;
}

export interface FlowChecklistStep {
  slot_id: string;
  label: string;
  required: boolean;
  recommended_template_ids: string[];
  recommended_atom_types: string[];
  default_template_id: string;
  alternative_template_ids: string[];
  input_requirements: string[];
  depends_on: string[];
  allow_empty_marker: boolean;
  category: string;
  guidance: string;
}

export interface FlowChecklist {
  scenario_id: string;
  label: string;
  description: string;
  version: string;
  steps: FlowChecklistStep[];
}

export async function listFlowChecklists(): Promise<FlowChecklistSummary[]> {
  const { data } = await api.get('/flow-checklists');
  return data;
}

export async function getFlowChecklist(scenarioId: string): Promise<FlowChecklist> {
  const { data } = await api.get(`/flow-checklists/${scenarioId}`);
  return data;
}

export interface HealthStatus {
  status: string;
  version: string;
  [key: string]: unknown;
}

export async function getHealth(): Promise<HealthStatus> {
  const { data } = await api.get('/health');
  return data;
}

export interface BackendDescription {
  backend_id: string;
  class_path: string;
  dependency_profile_id?: string;
  display_name: string;
  description: string;
  is_available: boolean;
  is_loaded: boolean;
}

export async function getBackends(): Promise<BackendDescription[]> {
  const { data } = await api.get('/backends');
  return data;
}

export interface SnapshotResult {
  snapshot_id: string;
  flow_hash: string;
  created_at: string;
}

export async function createSnapshot(projectId: string): Promise<SnapshotResult> {
  const { data } = await api.post(`/projects/${projectId}/snapshots`);
  return data;
}

export interface VersionHistoryEntry {
  revision: number;
  saved_at: string;
  reason: string;
  current: boolean;
  path: string;
}

export async function getVersionHistory(projectId: string): Promise<VersionHistoryEntry[]> {
  const { data } = await api.get(`/projects/${projectId}/version-history`);
  return data;
}

export async function restoreProjectRevision(projectId: string, revision: number): Promise<Project> {
  const { data } = await api.post(`/projects/${projectId}/bundle/restore/${revision}`);
  return data;
}

// --- Design History (FlowVCS) ---

export interface AuthorInfo {
  id: string;
  display_name: string;
}

export interface DesignCommitLogEntry {
  commit_id: string;
  parents: string[];
  semantic_flow_hash: string;
  message: string;
  author: AuthorInfo;
  created_at: string;
  reason: string;
}

export interface BranchInfo {
  name: string;
  commit_id: string;
  is_current: boolean;
}

export interface DesignHistoryStatus {
  head: DesignCommitLogEntry | null;
  branches: BranchInfo[];
  dirty: boolean;
}

export interface DiffChange {
  kind: 'node_added' | 'node_removed' | 'node_changed' | 'edge_added' | 'edge_removed' | 'edge_changed' | 'flow_hash_changed';
  node_id?: string;
  edge_id?: string;
  path?: string;
  before?: unknown;
  after?: unknown;
}

export interface DiffResult {
  from_commit: string;
  to_commit: string;
  from_flow_hash: string;
  to_flow_hash: string;
  changes: DiffChange[];
}

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

export interface MigrationReport {
  snapshots_imported: number;
  snapshots_skipped: number;
  revisions_imported: number;
  revisions_skipped: number;
  objects_deduplicated: number;
  warnings: string[];
  errors: string[];
  success: boolean;
}

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

export interface AIDraftFlow extends Record<string, unknown> {
  flow_id: string;
  name: string;
  description: string;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  metadata: {
    ai_generation: AIGenerationMetadata;
    [key: string]: unknown;
  };
}

export interface GenerateAIDraftRequest {
  scenario: AIDraftScenario;
  study_name?: string;
  data_format?: string;
  conditions?: string[];
  ai_settings?: {
    mode: 'template' | 'openai-compatible';
    provider: string;
    base_url: string;
    model: string;
    organization?: string;
    project?: string;
    temperature: number;
    max_tokens: number;
    timeout_seconds: number;
  };
}

export interface DraftReadiness {
  status: 'Ready' | 'Needs Attention' | 'Blocked';
  checks: Array<{ name: string; status: 'pass' | 'warn' | 'fail' | 'skip'; message: string }>;
}

export interface AIDraftValidation {
  status: 'draft_validated';
  flow_id: string;
  valid: boolean;
  errors: string[];
  warnings: string[];
  risks: Array<{
    risk_id: string;
    code: string;
    severity: string;
    domain: string;
    message: string;
    suggested_action: string;
  }>;
  readiness: DraftReadiness;
}

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
    return data.draft;
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
