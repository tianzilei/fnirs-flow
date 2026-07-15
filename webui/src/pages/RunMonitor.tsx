import { Fragment, useState } from 'react';
import { AlertTriangle, Boxes, CheckCircle2, ChevronDown, ChevronRight, Clock3, Copy, CopyCheck, FileJson, GitFork, Play, Radar, ShieldCheck, XCircle } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { useStore } from '../store';
import type { AtomExecutionSummary } from '../api/client';

const statusIcons: Record<string, typeof Clock3> = {
  completed: CheckCircle2,
  failed: XCircle,
  running: Radar,
  planned: Clock3,
};

export function RunMonitor() {
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const runs = useStore((s) => s.runs);
  const executeInfo = useStore((s) => s.executeInfo);
  const currentAttempt = useStore((s) => s.currentAttempt);
  const importStatus = useStore((s) => s.importStatus);
  const progressEvents = useStore((s) => s.progressEvents);
  const loading = useStore((s) => s.loading);
  const validation = useStore((s) => s.validation);
  const dryRun = useStore((s) => s.dryRun);
  const execute = useStore((s) => s.execute);
  const cancelExecution = useStore((s) => s.cancelExecution);
  const fork = useStore((s) => s.fork);
  const trustAtom = useStore((s) => s.trustAtom);
  const projectStatus = useStore(useShallow((s) => s.projectStatus()));
  const quarantined = (importStatus?.quarantined_atoms.length ?? 0) > 0;

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
            title={!canPlanRun ? 'Dry run requires a compiled flow, bound data, and no fatal validation risks' : 'Plan project runs'}
          >
            <CopyCheck size={16} />
            <span>{loading ? 'Running...' : 'Dry Run'}</span>
          </button>
          <button
            className="primary-button"
            onClick={execute}
            disabled={loading || !canPlanRun}
            title={hasFatalRisk ? 'Cannot execute: fatal validation risks detected' : 'Execute project'}
          >
            <Play size={16} />
            <span>{loading ? 'Executing...' : 'Execute'}</span>
          </button>
          {currentAttempt && ['queued', 'running', 'cancelling'].includes(currentAttempt.status) && (
            <button className="ghost-button" onClick={cancelExecution} disabled={currentAttempt.status === 'cancelling'}>
              <XCircle size={16} />
              <span>{currentAttempt.status === 'cancelling' ? 'Cancelling...' : 'Cancel'}</span>
            </button>
          )}
          {importStatus?.imported && importStatus.read_only && (
            <button className="ghost-button" onClick={fork} disabled={loading}>
              <GitFork size={16} />
              <span>Fork</span>
            </button>
          )}
        </div>
      </section>

      {importStatus?.imported && (
        <section className="notice-panel warning">
          <AlertTriangle size={18} />
          <div>
            <strong>Imported package</strong>
            <span>{importStatus.read_only ? 'Read-only package. Fork before editing.' : 'Editable imported project.'}</span>
          </div>
          {importStatus.quarantined_atoms.length > 0 && (
            <div className="quarantine-actions">
              {importStatus.quarantined_atoms.map((atomId) => (
                <button key={atomId} onClick={() => trustAtom(atomId)} disabled={loading}>
                  <ShieldCheck size={14} />
                  Trust {atomId}
                </button>
              ))}
            </div>
          )}
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
                {runs.map((run) => {
                  const Icon = statusIcons[run.status] || Clock3;
                  const isExpanded = expandedRunId === run.run_id;
                  const derivativeCount = run.artifacts?.filter((artifact) => artifact.path).length || 0;
                  return (
                    <Fragment key={run.run_id}>
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
                              onClick={() => setExpandedRunId(isExpanded ? null : run.run_id)}
                              aria-expanded={isExpanded}
                              title="Show atom outputs and derivative locations"
                            >
                              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                              {run.atom_results.filter((atom) => atom.status === 'completed').length}/{run.atom_results.length}
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
