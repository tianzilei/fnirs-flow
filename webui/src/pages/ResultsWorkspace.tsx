import { useState } from 'react';
import {
  Boxes, CheckCircle2, FileJson, FlaskConical,
  BarChart3, Copy, XCircle
} from 'lucide-react';
import { useStore } from '../store';

interface Artifact {
  type: string;
  path: string;
  checksum: string;
  run_id?: string;
}

export function ResultsWorkspace() {
  const runs = useStore((s) => s.runs);
  const executeInfo = useStore((s) => s.executeInfo);
  const [selectedTab, setSelectedTab] = useState<'artifacts' | 'qc' | 'channel' | 'roi' | 'group'>('artifacts');
  const [copiedPath, setCopiedPath] = useState<string | null>(null);

  const allArtifacts: Artifact[] = runs.flatMap((run) =>
    (run.artifacts || []).map((a) => ({ ...a, run_id: run.run_id }))
  );

  const completedRuns = runs.filter((r) => r.status === 'completed');
  const failedRuns = runs.filter((r) => r.status === 'failed');

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedPath(text);
    setTimeout(() => setCopiedPath(null), 2000);
  };

  return (
    <div className="page results-workspace work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Results</span>
          <h2>Results Workspace</h2>
        </div>
      </section>

      {!executeInfo && (
        <div className="empty-state">
          <FlaskConical size={48} />
          <p>No execution results yet. Run the analysis first to see results here.</p>
        </div>
      )}

      {executeInfo && (
        <>
          <section className="metrics-grid">
            <div className="metric">
              <Boxes size={18} />
              <span className="metric-value">{runs.length}</span>
              <span className="metric-label">Total Runs</span>
            </div>
            <div className="metric">
              <CheckCircle2 size={18} />
              <span className="metric-value">{completedRuns.length}</span>
              <span className="metric-label">Completed</span>
            </div>
            <div className="metric">
              <XCircle size={18} />
              <span className="metric-value">{failedRuns.length}</span>
              <span className="metric-label">Failed</span>
            </div>
            <div className="metric">
              <FileJson size={18} />
              <span className="metric-value">{allArtifacts.length}</span>
              <span className="metric-label">Artifacts</span>
            </div>
          </section>

          <section className="results-tabs">
            <div className="tab-bar">
              <button
                className={`tab ${selectedTab === 'artifacts' ? 'active' : ''}`}
                onClick={() => setSelectedTab('artifacts')}
              >
                <FileJson size={14} /> Artifacts
              </button>
              <button
                className={`tab ${selectedTab === 'qc' ? 'active' : ''}`}
                onClick={() => setSelectedTab('qc')}
              >
                <BarChart3 size={14} /> QC Results
              </button>
              <button
                className={`tab ${selectedTab === 'channel' ? 'active' : ''}`}
                onClick={() => setSelectedTab('channel')}
              >
                <BarChart3 size={14} /> Channel
              </button>
              <button
                className={`tab ${selectedTab === 'roi' ? 'active' : ''}`}
                onClick={() => setSelectedTab('roi')}
              >
                <BarChart3 size={14} /> ROI
              </button>
              <button
                className={`tab ${selectedTab === 'group' ? 'active' : ''}`}
                onClick={() => setSelectedTab('group')}
              >
                <BarChart3 size={14} /> Group
              </button>
            </div>

            <div className="tab-content">
              {selectedTab === 'artifacts' && (
                <div className="artifacts-panel">
                  {allArtifacts.length > 0 ? (
                    <table className="artifacts-table">
                      <thead>
                        <tr>
                          <th>Type</th>
                          <th>Path</th>
                          <th>Checksum</th>
                          <th>Run</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {allArtifacts.map((artifact, i) => (
                          <tr key={i}>
                            <td>
                              <span className="artifact-type-badge">{artifact.type}</span>
                            </td>
                            <td>
                              <code className="artifact-path">{artifact.path}</code>
                            </td>
                            <td>
                              <code className="artifact-checksum">{artifact.checksum?.slice(0, 12)}</code>
                            </td>
                            <td>{artifact.run_id || '-'}</td>
                            <td>
                              <button
                                className="ghost-button small"
                                onClick={() => copyToClipboard(artifact.path)}
                                title="Copy path"
                              >
                                {copiedPath === artifact.path ? <CheckCircle2 size={14} /> : <Copy size={14} />}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div className="empty-state compact">
                      <p>No artifacts generated yet.</p>
                    </div>
                  )}
                </div>
              )}

              {selectedTab === 'qc' && (
                <div className="results-placeholder">
                  <BarChart3 size={48} />
                  <h3>QC Results</h3>
                  <p>SCI/Coupling, CV, SNR, Saturation, Source-Detector Distance</p>
                  <p className="muted">Requires backend API: GET /api/projects/{"{id}"}/results/qc</p>
                </div>
              )}

              {selectedTab === 'channel' && (
                <div className="results-placeholder">
                  <BarChart3 size={48} />
                  <h3>Channel Results</h3>
                  <p>Per-channel beta values, statistics, and contrast results</p>
                  <p className="muted">Requires backend API: GET /api/projects/{"{id}"}/results/channel</p>
                </div>
              )}

              {selectedTab === 'roi' && (
                <div className="results-placeholder">
                  <BarChart3 size={48} />
                  <h3>ROI Results</h3>
                  <p>Region-of-interest aggregated results</p>
                  <p className="muted">Requires backend API: GET /api/projects/{"{id}"}/results/roi</p>
                </div>
              )}

              {selectedTab === 'group' && (
                <div className="results-placeholder">
                  <BarChart3 size={48} />
                  <h3>Group Summary</h3>
                  <p>Group-level statistics and summary</p>
                  <p className="muted">Requires backend API: GET /api/projects/{"{id}"}/results/group</p>
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
