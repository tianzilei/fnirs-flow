import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import {
  Boxes, CheckCircle2, FileJson, FlaskConical,
  BarChart3, Copy, XCircle
} from 'lucide-react';
import { useStore } from '../store';
import { selectExecuteInfo, selectRuns } from '../features/execution/store';
import { selectImportStatus } from '../features/packages/store';
import { selectProject } from '../features/project/store';
import { formatApiError, getProjectResults, type ArtifactSummary, type ProjectResults } from '../api/client';
import { sanitizeSvg } from '../utils/sanitizeSvg';

interface LocatedArtifact extends ArtifactSummary {
  run_id?: string;
}

const RESULT_TABS = [
  { id: 'artifacts', label: 'Artifacts', icon: FileJson },
  { id: 'qc', label: 'QC Results', icon: BarChart3 },
  { id: 'channel', label: 'Channel', icon: BarChart3 },
  { id: 'roi', label: 'ROI', icon: BarChart3 },
  { id: 'group', label: 'Group', icon: BarChart3 },
] as const;

type ResultTab = typeof RESULT_TABS[number]['id'];

export function ResultsWorkspace() {
  const runs = useStore(selectRuns);
  const executeInfo = useStore(selectExecuteInfo);
  const project = useStore(selectProject);
  const importStatus = useStore(selectImportStatus);
  const flow = useStore((state) => state.flow);
  const processedHb = (((flow.data_semantics as Record<string, unknown>) || {}).branch === 'vendor_processed_hb');
  const [selectedTab, setSelectedTab] = useState<ResultTab>('artifacts');
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [copiedPath, setCopiedPath] = useState<string | null>(null);
  const [backendResults, setBackendResults] = useState<ProjectResults | null>(null);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [resultsError, setResultsError] = useState('');

  useEffect(() => {
    if (!project || selectedTab === 'artifacts') {
      setBackendResults(null);
      setResultsLoading(false);
      setResultsError('');
      return;
    }
    let active = true;
    setBackendResults(null);
    setResultsLoading(true);
    setResultsError('');
    getProjectResults(project.id, selectedTab)
      .then((result) => {
        if (active) setBackendResults(result);
      })
      .catch((error) => {
        if (active) setResultsError(formatApiError(error));
      })
      .finally(() => {
        if (active) setResultsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [project, selectedTab]);

  const allArtifacts: LocatedArtifact[] = runs.flatMap((run) =>
    (run.artifacts || []).filter((artifact) => artifact.path).map((a) => ({ ...a, run_id: run.run_id }))
  );
  const atomRows = runs.flatMap((run) =>
    (run.atom_results || []).map((atom) => ({
      run_id: run.run_id,
      atom,
      hasLegacyUnassignedFiles: Boolean(
        run.artifacts?.some((artifact) => artifact.path && !artifact.atom_id)
      ),
    }))
  );

  const completedRuns = runs.filter((r) => r.status === 'completed');
  const failedRuns = runs.filter((r) => r.status === 'failed');

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedPath(text);
    setTimeout(() => setCopiedPath(null), 2000);
  };

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % RESULT_TABS.length;
    if (event.key === 'ArrowLeft') nextIndex = (index - 1 + RESULT_TABS.length) % RESULT_TABS.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = RESULT_TABS.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = RESULT_TABS[nextIndex].id;
    setSelectedTab(nextTab);
    tabRefs.current[nextIndex]?.focus();
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
          <p>
            {importStatus?.imported
              ? 'Imported package results are available in the result tabs below.'
              : 'No execution results yet. Run the analysis first to see results here.'}
          </p>
        </div>
      )}

      {executeInfo && (
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
      )}

      {project && (
          <section className="results-tabs">
            <div className="tab-bar" role="tablist" aria-label="Result views">
              {RESULT_TABS.map((tab, index) => {
                const Icon = tab.icon;
                const selected = selectedTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    ref={(element) => { tabRefs.current[index] = element; }}
                    id={`results-tab-${tab.id}`}
                    role="tab"
                    aria-selected={selected}
                    aria-controls={`results-panel-${tab.id}`}
                    tabIndex={selected ? 0 : -1}
                    className={`tab ${selected ? 'active' : ''}`}
                    onClick={() => setSelectedTab(tab.id)}
                    onKeyDown={(event) => handleTabKeyDown(event, index)}
                  >
                    <Icon size={14} aria-hidden="true" /> {tab.label}
                  </button>
                );
              })}
            </div>

            <div
              className="tab-content"
              id={`results-panel-${selectedTab}`}
              role="tabpanel"
              aria-labelledby={`results-tab-${selectedTab}`}
              tabIndex={0}
            >
              {selectedTab === 'artifacts' && (
                <div className="artifacts-panel">
                  <div className="results-section-heading">
                    <h3>Atom derivative locations</h3>
                    <span>Every executed atom is listed, including in-memory-only and skipped outputs.</span>
                  </div>
                  {atomRows.length > 0 ? (
                    <table className="artifacts-table atom-output-table">
                      <thead>
                        <tr>
                          <th>Run</th>
                          <th>Atom</th>
                          <th>Status</th>
                          <th>Output</th>
                          <th>Derivative location</th>
                        </tr>
                      </thead>
                      <tbody>
                        {atomRows.map(({ run_id, atom, hasLegacyUnassignedFiles }) => {
                          const files = (atom.artifacts || []).filter((artifact) => artifact.path);
                          const outputType = Object.values(atom.output_handles || {}).filter(Boolean).join(', ');
                          return (
                            <tr key={`${run_id}-${atom.atom_id}`}>
                              <td>{run_id}</td>
                              <td><strong>{atom.atom_id}</strong></td>
                              <td><span className={`status-chip ${atom.status}`}>{atom.status}</span></td>
                              <td>{outputType || '-'}</td>
                              <td>
                                {files.length > 0 ? (
                                  <div className="table-location-list">
                                    {files.map((artifact) => (
                                      <div key={`${artifact.artifact_id}-${artifact.path}`}>
                                        {artifact.relative_path && <code>{artifact.relative_path}</code>}
                                        <code title="Portable project URI">{artifact.uri || artifact.path}</code>
                                        {artifact.resolved_path && <code title="Resolved local path">{artifact.resolved_path}</code>}
                                        <button
                                          className="ghost-button small"
                                          onClick={() => copyToClipboard(artifact.uri || artifact.path)}
                                          title="Copy portable URI"
                                        >
                                          {copiedPath === artifact.path ? <CheckCircle2 size={14} /> : <Copy size={14} />}
                                        </button>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <span className="no-file-label">
                                    {hasLegacyUnassignedFiles
                                      ? 'Legacy attempt · rerun to map files to Atoms'
                                      : atom.status === 'skipped'
                                      ? 'Skipped · no derivative file'
                                      : atom.status === 'failed'
                                        ? 'Failed · no derivative file'
                                        : outputType
                                          ? 'In-memory result only'
                                          : 'No derivative file generated'}
                                  </span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  ) : (
                    <div className="empty-state compact"><p>No atom results available yet.</p></div>
                  )}

                  <div className="results-section-heading artifact-index-heading">
                    <h3>Derivative file index</h3>
                    <span>Portable project URIs are canonical; resolved local paths are shown when available.</span>
                  </div>
                  {allArtifacts.length > 0 ? (
                    <table className="artifacts-table">
                      <thead>
                        <tr>
                          <th>Type</th>
                          <th>Path</th>
                          <th>Integrity SHA-256</th>
                          <th>Run</th>
                          <th>Atom</th>
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
                              {artifact.relative_path && <code className="artifact-relative-path">{artifact.relative_path}</code>}
                              <code className="artifact-path">{artifact.uri || artifact.path}</code>
                              {artifact.resolved_path && <code title="Resolved local path">{artifact.resolved_path}</code>}
                            </td>
                            <td>
                              <code className="artifact-checksum">{artifact.checksum?.slice(0, 12)}</code>
                            </td>
                            <td>{artifact.run_id || '-'}</td>
                            <td>{artifact.atom_id || artifact.step_id || '-'}</td>
                            <td>
                              <button
                                className="ghost-button small"
                                onClick={() => copyToClipboard(artifact.uri || artifact.path)}
                                title="Copy portable URI"
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
                <ResultDataPanel title="QC Results" result={backendResults} loading={resultsLoading} error={resultsError} />
              )}

              {selectedTab === 'channel' && (
                <ResultDataPanel title="Channel Results" result={backendResults} loading={resultsLoading} error={resultsError} />
              )}

              {selectedTab === 'roi' && (
                processedHb
                  ? <div className="empty-state compact"><p>ROI unavailable: no versioned, hashed channel-to-ROI mapping is bound. No MNI atlas was selected automatically.</p></div>
                  : <ResultDataPanel title="ROI Results" result={backendResults} loading={resultsLoading} error={resultsError} />
              )}

              {selectedTab === 'group' && (
                <ResultDataPanel title="Group Summary" result={backendResults} loading={resultsLoading} error={resultsError} />
              )}
            </div>
          </section>
      )}
    </div>
  );
}

function ResultDataPanel({
  title,
  result,
  loading,
  error,
}: {
  title: string;
  result: ProjectResults | null;
  loading: boolean;
  error: string;
}) {
  if (loading) return <div className="loading-state">Loading {title}...</div>;
  if (error) return <div className="error-message">{error}</div>;
  if (!result || result.file_count === 0) {
    if (!result?.figures?.length) {
      const emptyCopy = title === 'ROI Results'
        ? 'No ROI result files are available. This can happen when the selected demo flow completes channel and group summaries without ROI-level exports.'
        : `No ${title.toLowerCase()} files available.`;
      return (
        <div className="artifacts-panel result-data-panel">
          <div className="results-section-heading">
            <h3>{title}</h3>
          </div>
          <div className="empty-state compact"><p>{emptyCopy}</p></div>
        </div>
      );
    }
  }
  const figures = result.figures || [];
  const rows: Array<Record<string, unknown>> = result.files.flatMap((file) => {
    const data = file.data as Record<string, unknown> | unknown[];
    const values = Array.isArray(data)
      ? data
      : Array.isArray((data as Record<string, unknown>).summaries)
        ? (data as Record<string, unknown>).summaries as unknown[]
        : [data];
    return values.map((value): Record<string, unknown> => ({
      __file: file.path,
      ...(value && typeof value === 'object' ? value as Record<string, unknown> : { value }),
    }));
  });
  const previewRows = selectPreviewRows(rows, 100);
  const columns = Array.from(new Set(previewRows.flatMap((row) => Object.keys(row)))).slice(0, 10);
  return (
    <div className="artifacts-panel result-data-panel">
      <div className="results-section-heading">
        <h3>{title}</h3>
      </div>
      <p className="muted">{result.file_count} files · {rows.length} preview rows{figures.length ? ` · ${figures.length} figures` : ''}{result.truncated || result.files.some((file) => file.rows_truncated) ? ' · preview limited' : ''}</p>
      {figures.length > 0 && (
        <div className="result-figures">
          {figures.map((figure) => (
            <figure key={figure.path}>
              <figcaption>{figure.path}</figcaption>
              <div className="result-svg-frame" dangerouslySetInnerHTML={{ __html: sanitizeSvg(figure.svg) }} />
            </figure>
          ))}
        </div>
      )}
      {rows.length > 0 && (
        <table className="artifacts-table">
          <thead><tr>{columns.map((column) => <th key={column}>{column.replace(/^__/, '')}</th>)}</tr></thead>
          <tbody>
            {previewRows.map((row, index) => (
              <tr key={`${String(row.__file)}-${index}`}>
                {columns.map((column) => (
                  <td key={column}><code>{formatCell(row[column])}</code></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function selectPreviewRows(rows: Array<Record<string, unknown>>, limit: number) {
  if (rows.length <= limit) return rows;
  const selected: Array<Record<string, unknown>> = [];
  const selectedIndexes = new Set<number>();
  const seenFiles = new Set<string>();
  rows.forEach((row, index) => {
    const file = String(row.__file || '');
    if (selected.length < limit && !seenFiles.has(file)) {
      seenFiles.add(file);
      selected.push(row);
      selectedIndexes.add(index);
    }
  });
  rows.forEach((row, index) => {
    if (selected.length < limit && !selectedIndexes.has(index)) selected.push(row);
  });
  return selected;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
