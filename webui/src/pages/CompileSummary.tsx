import { Layers, FileCode2, GitBranch, Hash } from 'lucide-react';
import { useStore } from '../store';
import { DagLayerPreview } from '../components/DagLayerPreview';

export function CompileSummary() {
  const result = useStore((s) => s.compileResult);
  const loading = useStore((s) => s.loading);
  const snapshot = useStore((s) => s.snapshot);
  const compile = useStore((s) => s.compile);
  const createSnapshot = useStore((s) => s.createSnapshot);

  return (
    <div className="page compile-summary work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Readiness</span>
          <h2>Compile Summary</h2>
        </div>
        <div className="page-actions">
          <button className="primary-button" onClick={compile} disabled={loading}>
            {loading ? 'Compiling...' : 'Compile Flow'}
          </button>
        </div>
      </section>

      {result && (
        <div className="compile-results">
          <section className="metrics-grid">
            <div className="metric">
              <Hash size={18} />
              <span className="metric-value">{result.flow_id || '-'}</span>
              <span className="metric-label">Flow ID</span>
            </div>
            <div className="metric">
              <GitBranch size={18} />
              <span className="metric-value">{result.flow_hash?.slice(0, 12) || '-'}</span>
              <span className="metric-label">Flow Hash</span>
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
            <DagLayerPreview />
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
                  <div><dt>Flow Hash</dt><dd><code>{snapshot.flow_hash}</code></dd></div>
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
        <div className="empty-state">
          <p>Click "Compile Flow" to generate the execution plan and DAG.</p>
        </div>
      )}
    </div>
  );
}
