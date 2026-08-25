import { Fragment, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Boxes, CheckCircle2, ChevronDown, ChevronRight, Clock3, Copy, CopyCheck, FileJson, GitFork, Play, Radar, ShieldCheck, XCircle } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { useStore } from '../store';
import {
  selectCurrentAttempt,
  selectExecuteInfo,
  selectProgressEvents,
  selectRuns,
} from '../features/execution/store';
import { selectImportStatus } from '../features/packages/store';
import { getProjectResults, type AtomExecutionSummary } from '../api/client';

interface ProcessedQcRow {
  fnirs_record_id?: string;
  model_id?: string;
  channel?: string;
  chromophore?: string;
  solver_requested?: string;
  solver_effective?: string;
  ar1_rho?: string;
  ar_iterations?: string;
  ar_converged?: string;
  irls_iterations?: string;
  irls_converged?: string;
  low_weight_fraction?: string;
  rank?: string;
  condition_number?: string;
  residual_df?: string;
  covariance_status?: string;
  qc_status?: string;
  reason_code?: string;
}

const statusIcons: Record<string, typeof Clock3> = {
  completed: CheckCircle2,
  failed: XCircle,
  running: Radar,
  planned: Clock3,
};

export function RunMonitor() {
  const navigate = useNavigate();
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [processedQcRows, setProcessedQcRows] = useState<ProcessedQcRow[]>([]);
  const [processedQcFilter, setProcessedQcFilter] = useState<'all' | 'pass' | 'fail'>('all');
  const runs = useStore(selectRuns);
  const executeInfo = useStore(selectExecuteInfo);
  const currentAttempt = useStore(selectCurrentAttempt);
  const importStatus = useStore(selectImportStatus);
  const progressEvents = useStore(selectProgressEvents);
  const loading = useStore((s) => s.loading);
  const validation = useStore((s) => s.validation);
  const dryRun = useStore((s) => s.dryRun);
  const dryRunResult = useStore((s) => s.dryRunResult);
  const flow = useStore((s) => s.flow);
  const project = useStore((s) => s.project);
  const processedHb = (((flow.data_semantics as Record<string, unknown>) || {}).branch === 'vendor_processed_hb');
  const processedSummary = (dryRunResult?.summary?.processed_hb || dryRunResult?.summary || {}) as Record<string, unknown>;
  const execute = useStore((s) => s.execute);
  const cancelExecution = useStore((s) => s.cancelExecution);
  const fork = useStore((s) => s.fork);
  const trustAtom = useStore((s) => s.trustAtom);
  const projectStatus = useStore(useShallow((s) => s.projectStatus()));
  const quarantinedAtoms = Array.from(new Set([
    ...(importStatus?.quarantined_atoms ?? []),
    ...projectStatus.quarantinedAtoms,
  ]));
  const quarantined = quarantinedAtoms.length > 0;

  useEffect(() => {
    if (!processedHb || !project?.id || runs.length === 0) return;
    let active = true;
    getProjectResults(project.id, 'qc').then((result) => {
      if (!active) return;
      const rows = result.files
        .filter((file) => file.path.endsWith('residual_qc.csv') || file.path.endsWith('design_matrix_manifest.csv'))
        .flatMap((file) => Array.isArray(file.data) ? file.data as ProcessedQcRow[] : []);
      setProcessedQcRows(rows);
    }).catch(() => {
      if (active) setProcessedQcRows([]);
    });
    return () => { active = false; };
  }, [processedHb, project?.id, runs.length, currentAttempt?.completed_at]);

  const displayedProcessedQcRows = processedQcRows.filter((row) => {
    if (processedQcFilter === 'pass') return (row.qc_status || 'pass') === 'pass';
    if (processedQcFilter === 'fail') return row.qc_status === 'fail' || Boolean(row.reason_code);
    return true;
  });

  const handleFork = async () => {
    const newProject = await fork();
    if (newProject) navigate(`/projects/${newProject.id}/flow`);
  };

  const hasFatalRisk = validation?.risks?.some(
    (r: Record<string, unknown>) => r.severity === 'fatal'
  ) ?? false;
  const canPlanRun = projectStatus.compiled && projectStatus.dataDiscovered && !quarantined && !hasFatalRisk;
  const completed = runs.filter((run) => run.status === 'completed').length;
  const failed = runs.filter((run) => run.status === 'failed').length;
  const artifacts = runs.reduce(
    (count, run) => count + (run.artifacts?.filter((artifact) => artifact.path).length || 0),
    0
  );
  const latestEvents = progressEvents.slice(-8).reverse();

  return (
    <div className="page run-monitor work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Execution</span>
          <h2>Run Monitor</h2>
        </div>
        <div className="page-actions">
          <button
            className="ghost-button"
            onClick={dryRun}
            disabled={loading || !canPlanRun}
            type="button"
            aria-label="Dry run project"
            title={!canPlanRun ? 'Dry run requires a compiled flow, bound data, and no fatal validation risks' : 'Plan project runs'}
          >
            <CopyCheck size={16} />
            <span>{loading ? 'Running...' : 'Dry Run'}</span>
          </button>
          <button
            className="primary-button"
            onClick={execute}
            disabled={loading || !canPlanRun}
            type="button"
            aria-label="Execute project"
            title={hasFatalRisk ? 'Cannot execute: fatal validation risks detected' : 'Execute project'}
          >
            <Play size={16} />
            <span>{loading ? 'Executing...' : 'Execute'}</span>
          </button>
          {currentAttempt && ['queued', 'running', 'cancelling'].includes(currentAttempt.status) && (
            <button className="ghost-button" onClick={cancelExecution} disabled={currentAttempt.status === 'cancelling'} type="button">
              <XCircle size={16} />
              <span>{currentAttempt.status === 'cancelling' ? 'Cancelling...' : 'Cancel'}</span>
            </button>
          )}
          {importStatus?.imported && importStatus.read_only && (
            <button className="ghost-button" onClick={handleFork} disabled={loading} type="button">
              <GitFork size={16} />
              <span>Fork</span>
            </button>
          )}
        </div>
      </section>

      {(importStatus?.imported || quarantined) && (
        <section className="notice-panel warning">
          <AlertTriangle size={18} />
          <div>
            <strong>{importStatus?.imported ? 'Imported package' : 'Local Atom review required'}</strong>
            <span>{importStatus?.imported
              ? (importStatus.read_only ? 'Read-only package. Fork before editing.' : 'Editable imported project.')
              : 'Review each local Atom definition and capability manifest before execution.'}</span>
          </div>
          {quarantinedAtoms.length > 0 && (
            <div className="quarantine-actions">
              {quarantinedAtoms.map((atomId) => (
                <button key={atomId} onClick={() => trustAtom(atomId)} disabled={loading}>
                  <ShieldCheck size={14} />
                  Trust {atomId}
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      {processedHb && (
        <section className="notice-panel warning processed-hb-monitor">
          <AlertTriangle size={18} />
          <div>
            <strong>Experimental vendor-processed Hb</strong>
            <span>Absolute units are unverified. Monitor requested/effective solver, AR and IRLS convergence, design rank, and covariance status for every channel/chromophore.</span>
            {Object.keys(processedSummary).length > 0 && (
              <ProcessedDryRunSummary summary={processedSummary} />
            )}
            {processedQcRows.length > 0 && (
              <div className="processed-hb-details">
                <div className="processed-hb-filter-row">
                  <label htmlFor="processed-qc-filter">QC status</label>
                  <select id="processed-qc-filter" value={processedQcFilter} onChange={(event) => setProcessedQcFilter(event.target.value as typeof processedQcFilter)}>
                    <option value="all">All</option><option value="pass">Pass</option><option value="fail">Fail</option>
                  </select>
                </div>
                <div className="metadata-table-scroll">
                  <table className="runs-table processed-qc-table">
                    <thead><tr><th>Record / model</th><th>Series</th><th>Solver</th><th>AR(1)</th><th>IRLS</th><th>Design</th><th>Covariance</th><th>QC</th></tr></thead>
                    <tbody>{displayedProcessedQcRows.map((row, index) => (
                      <tr key={`${row.fnirs_record_id}-${row.model_id}-${row.channel}-${row.chromophore}-${index}`}>
                        <td><strong>{row.fnirs_record_id || '-'}</strong><span className="muted-cell">{row.model_id || '-'}</span></td>
                        <td>{[row.channel, row.chromophore].filter(Boolean).join(' / ') || 'model'}</td>
                        <td>{row.solver_requested ? `${row.solver_requested} → ${row.solver_effective}` : '-'}</td>
                        <td>{row.ar1_rho ? `ρ ${row.ar1_rho}; ${row.ar_iterations || 0} iter; ${row.ar_converged}` : '-'}</td>
                        <td>{row.irls_iterations ? `${row.irls_iterations} iter; ${row.irls_converged}; low ${row.low_weight_fraction}` : '-'}</td>
                        <td>{row.rank ? `rank ${row.rank}; κ ${row.condition_number}; df ${row.residual_df}` : '-'}</td>
                        <td>{row.covariance_status || '-'}</td>
                        <td><span className={`status-chip ${row.qc_status || (row.reason_code ? 'failed' : 'completed')}`}>{row.qc_status || (row.reason_code ? 'fail' : 'pass')}</span>{row.reason_code && <span className="muted-cell">{row.reason_code}</span>}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      <section className="metrics-grid">
        <Metric icon={Boxes} label="Runs" value={runs.length} />
        <Metric icon={CheckCircle2} label="Completed" value={completed} />
        <Metric icon={XCircle} label="Failed" value={failed} />
        <Metric icon={FileJson} label="Derivative files" value={artifacts} />
      </section>

      <section className="run-grid">
        <div className="run-table-panel">
          <div className="panel-heading">
            <h3>Runs</h3>
            {currentAttempt
              ? <span>Attempt {currentAttempt.attempt_id} · {currentAttempt.status}</span>
              : executeInfo && <span>Attempt {executeInfo.attempt_id}</span>}
          </div>
          {runs.length > 0 ? (
            <table className="runs-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Run</th>
                  <th>Atoms</th>
                  <th>Artifacts</th>
                  <th>Started</th>
                  <th>Completed</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run, index) => {
                  const Icon = statusIcons[run.status] || Clock3;
                  const derivativeCount = run.artifacts?.filter((artifact) => artifact.path).length || 0;
                  const skippedAtoms = run.atom_results?.filter((atom) => atom.status === 'skipped').length || 0;
                  const runKey = run.run_id || `${run.subject || 'run'}-${run.session || 'session'}-${run.run || index}`;
                  const isExpanded = expandedRunId === runKey;
                  return (
                    <Fragment key={runKey}>
                      <tr>
                        <td>
                          <span className={`status-chip ${run.status}`}>
                            <Icon size={14} />
                            {run.status}
                          </span>
                        </td>
                        <td>
                          <strong>{run.run_id}</strong>
                          <span className="muted-cell">{[run.subject, run.session, run.run].filter(Boolean).join(' / ')}</span>
                        </td>
                        <td>
                          {run.atom_results && run.atom_results.length > 0 ? (
                            <button
                              className="atom-count-button"
                              onClick={() => setExpandedRunId(isExpanded ? null : runKey)}
                              aria-expanded={isExpanded}
                              aria-label={`Show atom details for ${run.run_id || runKey}`}
                              type="button"
                              title="Show atom outputs and derivative locations"
                            >
                              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                              {run.atom_results.filter((atom) => atom.status === 'completed').length}/{run.atom_results.length}
                              {skippedAtoms > 0 && <span className="atom-count-note">{skippedAtoms} skipped</span>}
                            </button>
                          ) : '-'}
                        </td>
                        <td>{derivativeCount || '-'}</td>
                        <td>{run.started_at ? new Date(run.started_at).toLocaleTimeString() : '-'}</td>
                        <td>{run.completed_at ? new Date(run.completed_at).toLocaleTimeString() : '-'}</td>
                      </tr>
                      {isExpanded && run.atom_results && (
                        <tr className="atom-results-row">
                          <td colSpan={6}>
                            <div className="atom-results-list">
                              {run.atom_results.map((atom) => (
                                <AtomResultDetails
                                  key={atom.atom_id}
                                  atom={atom}
                                  hasLegacyUnassignedFiles={Boolean(
                                    run.artifacts?.some((artifact) => artifact.path && !artifact.atom_id)
                                  )}
                                />
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div className="empty-state compact">
              <div className="run-empty-guide">
                <strong>No runs yet.</strong>
                <span>{canPlanRun ? 'Use Dry Run to preview planned subject/session runs.' : 'Complete the readiness checks before planning execution.'}</span>
                <div className="readiness-checklist compact-list">
                  <CheckItem done={projectStatus.compiled} label="Compiled plan" />
                  <CheckItem done={projectStatus.dataDiscovered} label="Bound data" />
                  <CheckItem done={!hasFatalRisk} label="No fatal validation risks" />
                  <CheckItem done={!quarantined} label="No quarantined atoms" />
                </div>
              </div>
            </div>
          )}
        </div>

        <aside className="run-side-panel">
          {executeInfo && (
            <div className="summary-block">
              <h3>Execution Summary</h3>
              <dl>
                <div><dt>Successful</dt><dd>{executeInfo.successful}</dd></div>
                <div><dt>Failed</dt><dd>{executeInfo.failed}</dd></div>
                <div><dt>Failures</dt><dd>{executeInfo.failure_ids.length ? executeInfo.failure_ids.join(', ') : 'None'}</dd></div>
              </dl>
            </div>
          )}

          <div className="summary-block">
            <h3>Progress Stream</h3>
            {latestEvents.length > 0 ? (
              <div className="event-list">
                {latestEvents.map((event, index) => (
                  <div key={`${event.type}-${index}`} className="event-item">
                    <span className="event-dot" />
                    <div>
                      <strong>{String(event.type).replace(/_/g, ' ')}</strong>
                      {event.atom_id !== undefined && event.atom_id !== null ? <span>{String(event.atom_id)}</span> : null}
                      {event.successful !== undefined && <span>{String(event.successful)} successful / {String(event.failed)} failed</span>}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">No progress events yet.</p>
            )}
          </div>
        </aside>
      </section>
    </div>
  );
}

function ProcessedDryRunSummary({ summary }: { summary: Record<string, unknown> }) {
  const counts = (summary.counts || {}) as Record<string, number>;
  const estimands = (summary.estimands || {}) as Record<string, { eligible_record_pairs?: number }>;
  return (
    <div className="processed-hb-details">
      <div className="metrics-grid compact-metrics">
        <Metric icon={Boxes} label="Frozen total" value={counts.total || 0} />
        <Metric icon={CheckCircle2} label="Eligible" value={counts.eligible || 0} />
        <Metric icon={XCircle} label="Missing" value={counts.missing || 0} />
      </div>
      <div className="metadata-table-scroll">
        <table className="runs-table"><thead><tr><th>Model</th><th>Eligible record pairs</th></tr></thead>
          <tbody>{Object.entries(estimands).map(([model, value]) => <tr key={model}><td>{model}</td><td>{value.eligible_record_pairs ?? 0}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}

function CheckItem({ done, label }: { done: boolean; label: string }) {
  return <div className={`check-item ${done ? 'done' : ''}`}>{done ? '✓' : '○'} {label}</div>;
}

function AtomResultDetails({
  atom,
  hasLegacyUnassignedFiles,
}: {
  atom: AtomExecutionSummary;
  hasLegacyUnassignedFiles: boolean;
}) {
  const derivativeFiles = (atom.artifacts || []).filter((artifact) => artifact.path);
  const outputType = Object.values(atom.output_handles || {}).filter(Boolean).join(', ');
  const emptyMessage = hasLegacyUnassignedFiles
    ? 'This older attempt has run-level files but no Atom association; rerun it to create the mapping.'
    : atom.status === 'skipped'
    ? 'No derivative file: this atom was skipped.'
    : atom.status === 'failed'
      ? 'No derivative file was produced before failure.'
      : outputType
        ? 'In-memory result only; no derivative file was generated.'
        : 'This atom did not generate a derivative file.';

  return (
    <div className="atom-result-card">
      <div className="atom-result-heading">
        <strong>{atom.atom_id}</strong>
        <span className={`status-chip ${atom.status}`}>{atom.status}</span>
        {outputType && <span className="atom-output-type">Output: {outputType}</span>}
      </div>
      {derivativeFiles.length > 0 ? (
        <div className="derivative-location-list">
          {derivativeFiles.map((artifact) => (
            <div className="derivative-location" key={`${artifact.artifact_id}-${artifact.path}`}>
              <div>
                <span>{artifact.type || 'Derivative file'}{artifact.exists === false ? ' · missing' : ''}</span>
                {artifact.relative_path && <code>{artifact.relative_path}</code>}
                <code title="Portable project URI">{artifact.uri || artifact.path}</code>
                {artifact.resolved_path && <code title="Resolved local path">{artifact.resolved_path}</code>}
              </div>
              <button
                className="ghost-button small"
                onClick={() => navigator.clipboard.writeText(artifact.uri || artifact.path)}
                title="Copy portable URI"
              >
                <Copy size={14} />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="atom-no-derivative">{emptyMessage}</p>
      )}
      {atom.error && <p className="atom-result-error">{atom.error}</p>}
      {!atom.error && atom.warnings?.length > 0 && (
        <p className="atom-result-warning">{atom.warnings.join(' ')}</p>
      )}
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Boxes; label: string; value: number }) {
  return (
    <div className="metric">
      <Icon size={18} />
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  );
}
