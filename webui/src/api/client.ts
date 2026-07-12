import axios from 'axios';

const API_BASE = '/api';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
});

export interface Project {
  id: string;
  name: string;
  description: string;
  flow_id: string;
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
}

export interface DiscoverResult {
  dataset_id: string;
  files: number;
  runs: number;
  local_root: string;
  source_url: string;
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
  });
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
    atom_results: Array<{
      atom_id: string;
      status: string;
      error?: string;
    }>;
    artifacts: Array<{
      type: string;
      path: string;
      checksum: string;
    }>;
  }>;
  failure_ids: string[];
}

export async function executeProject(projectId: string): Promise<ExecuteResult> {
  const { data } = await api.post(`/projects/${projectId}/execute`);
  return data;
}

export interface ImportStatus {
  imported: boolean;
  read_only: boolean;
  quarantined_atoms: string[];
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
  evidence_refs: string[];
}

export async function listAtomTemplates(): Promise<AtomTemplate[]> {
  const { data } = await api.get('/atom-templates');
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

export interface SnapshotResult {
  snapshot_id: string;
  flow_hash: string;
  created_at: string;
}

export async function createSnapshot(projectId: string): Promise<SnapshotResult> {
  const { data } = await api.post(`/projects/${projectId}/snapshots`);
  return data;
}
