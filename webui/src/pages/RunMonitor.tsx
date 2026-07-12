import { AlertTriangle, Boxes, CheckCircle2, Clock3, CopyCheck, FileJson, GitFork, Play, Radar, ShieldCheck, XCircle } from 'lucide-react';
import { useStore } from '../store';

const statusIcons: Record<string, typeof Clock3> = {
  completed: CheckCircle2,
  failed: XCircle,
  running: Radar,
  planned: Clock3,
};

export function RunMonitor() {
  const runs = useStore((s) => s.runs);
  const executeInfo = useStore((s) => s.executeInfo);
  const importStatus = useStore((s) => s.importStatus);
  const progressEvents = useStore((s) => s.progressEvents);
  const loading = useStore((s) => s.loading);
  const validation = useStore((s) => s.validation);
  const dryRun = useStore((s) => s.dryRun);
  const execute = useStore((s) => s.execute);
  const fork = useStore((s) => s.fork);
  const trustAtom = useStore((s) => s.trustAtom);

  const hasFatalRisk = validation?.risks?.some(
    (r: Record<string, unknown>) => r.severity === 'fatal'
  ) ?? false;
  const completed = runs.filter((run) => run.status === 'completed').length;
  const failed = runs.filter((run) => run.status === 'failed').length;
  const artifacts = runs.reduce((count, run) => count + (run.artifacts?.length || 0), 0);
  const latestEvents = progressEvents.slice(-8).reverse();

  return (
    <div className="page run-monitor work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Execution</span>
          <h2>Run Monitor</h2>
        </div>
        <div className="page-actions">
          <button className="ghost-button" onClick={dryRun} disabled={loading || (importStatus?.read_only ?? false)}>
            <CopyCheck size={16} />
            <span>{loading ? 'Running...' : 'Dry Run'}</span>
          </button>
          <button
            className="primary-button"
            onClick={execute}
            disabled={loading || (importStatus?.read_only ?? false) || hasFatalRisk}
            title={hasFatalRisk ? 'Cannot execute: fatal validation risks detected' : 'Execute project'}
          >
            <Play size={16} />
            <span>{loading ? 'Executing...' : 'Execute'}</span>
          </button>
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
        <Metric icon={FileJson} label="Artifacts" value={artifacts} />
      </section>

      <section className="run-grid">
        <div className="run-table-panel">
          <div className="panel-heading">
            <h3>Runs</h3>
            {executeInfo && <span>Attempt {executeInfo.attempt_id}</span>}
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
                  return (
                    <tr key={run.run_id}>
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
                          <span title={run.atom_results.map((atom) => `${atom.atom_id}: ${atom.status}${atom.error ? ` - ${atom.error}` : ''}`).join('\n')}>
                            {run.atom_results.filter((atom) => atom.status === 'completed').length}/{run.atom_results.length}
                          </span>
                        ) : '-'}
                      </td>
                      <td>{run.artifacts ? run.artifacts.length : '-'}</td>
                      <td>{run.started_at ? new Date(run.started_at).toLocaleTimeString() : '-'}</td>
                      <td>{run.completed_at ? new Date(run.completed_at).toLocaleTimeString() : '-'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div className="empty-state compact">
              <p>No runs yet.</p>
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

function Metric({ icon: Icon, label, value }: { icon: typeof Boxes; label: string; value: number }) {
  return (
    <div className="metric">
      <Icon size={18} />
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  );
}
