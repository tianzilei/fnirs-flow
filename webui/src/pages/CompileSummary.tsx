import { Layers, FileCode2, GitBranch, RotateCw } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useShallow } from 'zustand/react/shallow';
import { useStore } from '../store';
import { DagLayerPreview } from '../components/DagLayerPreview';
import { selectProjectStatus } from '../features/project/projectStatus';

export function CompileSummary() {
  const result = useStore((s) => s.compileResult);
  const loading = useStore((s) => s.loading);
  const snapshot = useStore((s) => s.snapshot);
  const compile = useStore((s) => s.compile);
  const createSnapshot = useStore((s) => s.createSnapshot);
  const validation = useStore((s) => s.validation);
  const status = useStore(useShallow(selectProjectStatus));
  const navigate = useNavigate();
  const { id: projectId } = useParams();
  const hasFatalRisk = validation?.risks.some((risk) => risk.severity === 'fatal') ?? false;
  const canCompile = !loading && !hasFatalRisk;

  return (
    <div className="page compile-summary work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Readiness</span>
          <h2>Compile Summary</h2>
        </div>
        <div className="page-actions">
          <button className="primary-button" onClick={compile} disabled={!canCompile}>
            {loading ? 'Compiling...' : 'Compile Flow'}
          </button>
        </div>
      </section>

      {result && (
        <div className="compile-results">
          <section className="metrics-grid">
            <div className="metric">
              <RotateCw size={18} />
              <span className="metric-value">{result.flow_id || '-'}</span>
              <span className="metric-label">Flow ID</span>
            </div>
            <div className="metric">
              <GitBranch size={18} />
              <span className="metric-value">{result.revision || '-'}</span>
              <span className="metric-label">Flow Revision</span>
            </div>
            <div className="metric">
              <Layers size={18} />
              <span className="metric-value">{result.steps ?? '-'}</span>
              <span className="metric-label">Steps</span>
            </div>
            <div className="metric">
              <FileCode2 size={18} />
              <span className="metric-value">{result.layers ?? '-'}</span>
              <span className="metric-label">DAG Layers</span>
            </div>
          </section>

          <section className="dag-preview-section">
            <DagLayerPreview layers={result.dag_layers} />
          </section>

          {result.output_files && result.output_files.length > 0 && (
            <section className="compiled-files-panel">
              <h3>Compiled Output Files</h3>
              <ul className="file-list">
                {result.output_files.map((file, i) => (
                  <li key={i} className="file-item">
                    <FileCode2 size={14} />
                    <code>{file}</code>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="snapshot-panel">
            <div className="snapshot-header">
              <h3>Project Snapshot</h3>
              <button className="ghost-button" onClick={createSnapshot} disabled={loading}>
                {loading ? 'Creating...' : 'Create Snapshot'}
              </button>
            </div>
            {snapshot && (
              <div className="snapshot-info">
                <dl>
                  <div><dt>Snapshot ID</dt><dd>{snapshot.snapshot_id}</dd></div>
                  <div><dt>Flow Revision</dt><dd><code>{snapshot.revision}</code></dd></div>
                  <div><dt>Created At</dt><dd>{new Date(snapshot.created_at).toLocaleString()}</dd></div>
                </dl>
              </div>
            )}
            {!snapshot && (
              <p className="muted">Create an immutable snapshot for execution and export tracking.</p>
            )}
          </section>
        </div>
      )}

      {!result && (
        <section className="workflow-panel">
          <div className="section-heading">
            <div>
              <h3>Before compiling</h3>
              <p className="muted">A compiled plan requires a saved flow with no fatal validation risks.</p>
            </div>
            <button className="primary-button" onClick={compile} disabled={!canCompile}>
              {loading ? 'Compiling...' : 'Compile Flow'}
            </button>
          </div>
          <div className="readiness-checklist">
            <CheckItem done={status.flowSaved} label="Flow saved" />
            <CheckItem done={status.validated && !hasFatalRisk} label="Validation passed without fatal risks" />
            <CheckItem done={status.dataDiscovered} label="Data discovered or relinked" />
          </div>
          {hasFatalRisk && projectId && (
            <button className="ghost-button" onClick={() => navigate(`/projects/${projectId}/checks`)}>
              Open validation fixes
            </button>
          )}
        </section>
      )}
    </div>
  );
}

function CheckItem({ done, label }: { done: boolean; label: string }) {
  return <div className={`check-item ${done ? 'done' : ''}`}>{done ? '✓' : '○'} {label}</div>;
}
