import { useEffect, useState } from 'react';
import { CheckCircle2 } from 'lucide-react';
import { formatApiError, listDatasets, type DiscoverResult } from '../api/client';
import { useStore } from '../store';

interface Dataset {
  id: string;
  name: string;
  description: string;
  sourceKind?: string;
}

const PREVIEW_COLUMN_LIMIT = 12;
const PREVIEW_ROW_LIMIT = 10;
const JOIN_LIST_LIMIT = 12;

const DEFAULT_DATASETS: Dataset[] = [
  { id: 'mne-fnirs-motor', name: 'MNE fNIRS Motor Task', description: 'Finger tapping experiment' },
];

const DATA_STEPS = [
  { id: 'dataset', label: 'Dataset' },
  { id: 'participants', label: 'Participants' },
  { id: 'join', label: 'Join Preview' },
  { id: 'ready', label: 'Ready' },
] as const;

type DataStep = typeof DATA_STEPS[number]['id'];

function formatMetadataValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'blank';
  if (Array.isArray(value)) return value.length ? value.map(formatMetadataValue).join(', ') : 'none';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function DataWorkspace() {
  const discover = useStore((s) => s.discover);
  const importParticipantTable = useStore((s) => s.importParticipantTable);
  const discoverResult = useStore((s) => s.discoverResult);
  const participantTableResult = useStore((s) => s.participantTableResult);
  const [activeStep, setActiveStep] = useState<DataStep>('dataset');
  const [selectedDataset, setSelectedDataset] = useState('');
  const [dataRoot, setDataRoot] = useState('');
  const [datasets, setDatasets] = useState<Dataset[]>(DEFAULT_DATASETS);
  const [datasetsLoading, setDatasetsLoading] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [participantPath, setParticipantPath] = useState('');
  const [idColumn, setIdColumn] = useState('participant_id');
  const [includeColumn, setIncludeColumn] = useState('include');
  const [groupColumn, setGroupColumn] = useState('group');
  const [labelColumn, setLabelColumn] = useState('group');
  const [siteColumn, setSiteColumn] = useState('site');
  const [scannerColumn, setScannerColumn] = useState('scanner_id');
  const [covariateColumns, setCovariateColumns] = useState('');
  const [sessionColumn, setSessionColumn] = useState('session');
  const [timepointColumn, setTimepointColumn] = useState('timepoint');
  const [pairIdColumn, setPairIdColumn] = useState('pair_id');
  const [dyadIdColumn, setDyadIdColumn] = useState('dyad_id');
  const [participantRoleColumn, setParticipantRoleColumn] = useState('participant_role');
  const [loading, setLoading] = useState(false);
  const [metadataLoading, setMetadataLoading] = useState(false);
  const [error, setError] = useState('');
  const previewColumns = participantTableResult
    ? participantTableResult.columns.slice(0, PREVIEW_COLUMN_LIMIT).map((column) => column.name)
    : [];
  const previewRows = participantTableResult?.preview_rows.slice(0, PREVIEW_ROW_LIMIT) || [];
  const roleEntries = Object.entries(participantTableResult?.column_role_map || {}).filter(([, value]) => {
    if (Array.isArray(value)) return value.length > 0;
    return value !== null && value !== undefined && value !== '';
  });
  const joinPreview = participantTableResult?.validation_report.join_preview;

  useEffect(() => {
    if (participantTableResult) setActiveStep('join');
    else if (discoverResult) setActiveStep('participants');
  }, [discoverResult, participantTableResult]);

  useEffect(() => {
    let active = true;
    setDatasetsLoading(true);
    listDatasets()
      .then((entries) => {
        if (!active) return;
        const nextDatasets = entries.map((entry) => ({
          id: entry.dataset_id,
          name: entry.name,
          description: entry.description || entry.url || entry.source_kind,
          sourceKind: entry.source_kind,
        }));
        if (nextDatasets.length > 0) {
          setDatasets(nextDatasets);
          setSelectedDataset((current) => current || nextDatasets[0].id);
        }
      })
      .catch((err) => {
        if (active) {
          setError(formatApiError(err));
        }
      })
      .finally(() => {
        if (active) setDatasetsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleDiscover = async () => {
    if (!selectedDataset) return;
    setLoading(true);
    setError('');
    try {
      await discover(selectedDataset, dataRoot.trim() || undefined);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  };

  const handleImportParticipantTable = async () => {
    if (!participantPath.trim()) return;
    setMetadataLoading(true);
    setError('');
    try {
      await importParticipantTable(participantPath.trim(), idColumn.trim() || 'participant_id', includeColumn.trim() || 'include', {
        group_column: groupColumn.trim() || 'group',
        label_column: labelColumn.trim() || groupColumn.trim() || 'group',
        site_column: siteColumn.trim() || 'site',
        scanner_column: scannerColumn.trim() || 'scanner_id',
        covariate_columns: covariateColumns
          .split(',')
          .map((column) => column.trim())
          .filter(Boolean),
        session_column: sessionColumn.trim() || 'session',
        timepoint_column: timepointColumn.trim() || 'timepoint',
        pair_id_column: pairIdColumn.trim() || 'pair_id',
        dyad_id_column: dyadIdColumn.trim() || 'dyad_id',
        participant_role_column: participantRoleColumn.trim() || 'participant_role',
      });
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setMetadataLoading(false);
    }
  };

  return (
    <div className="page data-import work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Dataset</span>
          <h2>Data Workspace</h2>
        </div>
      </section>

      <div className="workflow-stepper data-stepper">
        {DATA_STEPS.map((step, index) => {
          const done = (
            (step.id === 'dataset' && !!discoverResult)
            || (step.id === 'participants' && !!participantTableResult)
            || (step.id === 'join' && !!participantTableResult)
            || (step.id === 'ready' && !!participantTableResult && (joinPreview?.matched_subjects.length || 0) > 0)
          );
          return (
            <button
              key={step.id}
              className={`${activeStep === step.id ? 'active' : ''} ${done ? 'done' : ''}`}
              onClick={() => setActiveStep(step.id)}
            >
              {done ? <CheckCircle2 size={14} /> : <span>{index + 1}</span>}
              {step.label}
            </button>
          );
        })}
      </div>

      {error && <div className="error-message">{error}</div>}

      {activeStep === 'dataset' && (
        <section className="workflow-panel">
          <div className="section-heading">
            <div>
              <h3>Select and Discover Dataset</h3>
              <p className="muted">Choose a registered dataset, then discover local files and run metadata.</p>
            </div>
            <button className="primary-button" onClick={handleDiscover} disabled={!selectedDataset || loading}>
              {loading ? 'Discovering...' : 'Discover Dataset'}
            </button>
          </div>
          {datasetsLoading && <div className="panel-state">Loading registered datasets...</div>}
          <div className="dataset-list">
            {datasets.map((ds) => (
              <div
                key={ds.id}
                role="button"
                tabIndex={0}
                className={`dataset-card ${selectedDataset === ds.id ? 'selected' : ''}`}
                onClick={() => setSelectedDataset(ds.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setSelectedDataset(ds.id);
                  }
                }}
              >
                <h4>{ds.name}</h4>
                <p>{ds.description}</p>
                {ds.sourceKind && <span className="dataset-source">{ds.sourceKind}</span>}
              </div>
            ))}
          </div>
          <div className="metadata-grid dataset-root-grid">
            <label>
              Local dataset root
              <input
                value={dataRoot}
                onChange={(event) => setDataRoot(event.target.value)}
                placeholder="/path/to/BIDS-NIRS-Tapping-master"
              />
            </label>
          </div>
          {discoverResult && <DiscoverySummary result={discoverResult} />}
        </section>
      )}

      {activeStep === 'participants' && (
      <section className="metadata-import workflow-panel">
        <div className="section-heading">
          <div>
            <h3>Import Participant Metadata</h3>
            <p className="muted">Start with the table path and core identity columns. Advanced roles can stay at defaults.</p>
          </div>
          <button className="primary-button" onClick={handleImportParticipantTable} disabled={!participantPath.trim() || metadataLoading}>
            {metadataLoading ? 'Importing...' : 'Import Table'}
          </button>
        </div>
        <div className="metadata-grid">
          <label>
            Table path
            <input
              value={participantPath}
              onChange={(event) => setParticipantPath(event.target.value)}
              placeholder="D:\\data\\participants.tsv"
            />
          </label>
          <label>
            ID column
            <input value={idColumn} onChange={(event) => setIdColumn(event.target.value)} />
          </label>
          <label>
            Include column
            <input value={includeColumn} onChange={(event) => setIncludeColumn(event.target.value)} />
          </label>
          <label>
            Group column
            <input value={groupColumn} onChange={(event) => setGroupColumn(event.target.value)} />
          </label>
        </div>
        <button className="ghost-button compact" onClick={() => setAdvancedOpen((open) => !open)}>
          {advancedOpen ? 'Hide advanced column roles' : 'Show advanced column roles'}
        </button>
        {advancedOpen && (
        <div className="metadata-grid advanced">
          <label>
            Label column
            <input value={labelColumn} onChange={(event) => setLabelColumn(event.target.value)} />
          </label>
          <label>
            Site column
            <input value={siteColumn} onChange={(event) => setSiteColumn(event.target.value)} />
          </label>
          <label>
            Scanner column
            <input value={scannerColumn} onChange={(event) => setScannerColumn(event.target.value)} />
          </label>
          <label>
            Covariate columns
            <input value={covariateColumns} onChange={(event) => setCovariateColumns(event.target.value)} placeholder="age, sex" />
          </label>
          <label>
            Session column
            <input value={sessionColumn} onChange={(event) => setSessionColumn(event.target.value)} />
          </label>
          <label>
            Timepoint column
            <input value={timepointColumn} onChange={(event) => setTimepointColumn(event.target.value)} />
          </label>
          <label>
            Pair ID column
            <input value={pairIdColumn} onChange={(event) => setPairIdColumn(event.target.value)} />
          </label>
          <label>
            Dyad ID column
            <input value={dyadIdColumn} onChange={(event) => setDyadIdColumn(event.target.value)} />
          </label>
          <label>
            Participant role column
            <input value={participantRoleColumn} onChange={(event) => setParticipantRoleColumn(event.target.value)} />
          </label>
        </div>
        )}
      </section>
      )}

      {activeStep === 'join' && discoverResult && <DiscoverySummary result={discoverResult} />}

      {activeStep === 'join' && participantTableResult && (
        <div className="discovery-result">
          <h3>Participant Table</h3>
          <dl>
            <dt>Rows</dt>
            <dd>{participantTableResult.rows}</dd>
            <dt>Columns</dt>
            <dd>{participantTableResult.columns.length}</dd>
            <dt>Matched Subjects</dt>
            <dd>{participantTableResult.validation_report.join_preview.matched_subjects.length}</dd>
            <dt>Excluded Subjects</dt>
            <dd>{participantTableResult.validation_report.join_preview.excluded_subjects.length}</dd>
            <dt>Hash</dt>
            <dd>{String(participantTableResult.manifest.sha256 || '')}</dd>
          </dl>
          {participantTableResult.validation_report.errors.length > 0 && (
            <div className="error-message">{participantTableResult.validation_report.errors.join('; ')}</div>
          )}
          {participantTableResult.validation_report.warnings.length > 0 && (
            <div className="warning">{participantTableResult.validation_report.warnings.join('; ')}</div>
          )}

          <div className="metadata-result-block">
            <section className="metadata-subsection">
              <div className="metadata-subsection-heading">
                <h4>Column Roles</h4>
                <span>{roleEntries.length} mapped</span>
              </div>
              {roleEntries.length > 0 ? (
                <dl className="role-map-list">
                  {roleEntries.map(([role, value]) => (
                    <div key={role}>
                      <dt>{role}</dt>
                      <dd>{formatMetadataValue(value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="metadata-empty">No roles returned by the import.</p>
              )}
            </section>

            {joinPreview && (
              <section className="metadata-subsection">
                <div className="metadata-subsection-heading">
                  <h4>Join Preview</h4>
                  <span>{joinPreview.join_policy}</span>
                </div>
                <div className="join-preview-grid">
                  {[
                    ['Matched', joinPreview.matched_subjects],
                    ['Unmatched Results', joinPreview.unmatched_results],
                    ['Metadata Without Data', joinPreview.metadata_without_data],
                    ['Duplicate IDs', joinPreview.duplicate_ids],
                    ['Excluded', joinPreview.excluded_subjects],
                  ].map(([label, values]) => {
                    const items = values as string[];
                    return (
                      <div className="join-preview-group" key={label as string}>
                        <strong>{label as string}</strong>
                        <span>{items.length}</span>
                        {items.length > 0 && (
                          <ul>
                            {items.slice(0, JOIN_LIST_LIMIT).map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                            {items.length > JOIN_LIST_LIMIT && <li>{items.length - JOIN_LIST_LIMIT} more</li>}
                          </ul>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            <section className="metadata-subsection">
              <div className="metadata-subsection-heading">
                <h4>Columns</h4>
                <span>{participantTableResult.columns.length} total</span>
              </div>
              <div className="metadata-table-scroll">
                <table className="artifacts-table metadata-audit-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Missing</th>
                      <th>Unique</th>
                      <th>Sensitive</th>
                    </tr>
                  </thead>
                  <tbody>
                    {participantTableResult.columns.map((column) => (
                      <tr key={column.name}>
                        <td>{column.name}</td>
                        <td>{column.inferred_type}</td>
                        <td>{column.missing_count}</td>
                        <td>{column.unique_count}</td>
                        <td>{column.possible_sensitive ? 'yes' : 'no'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {previewColumns.length > 0 && (
              <section className="metadata-subsection">
                <div className="metadata-subsection-heading">
                  <h4>Preview Rows</h4>
                  <span>
                    {previewRows.length} rows, {previewColumns.length} of {participantTableResult.columns.length} columns
                  </span>
                </div>
                <div className="metadata-table-scroll">
                  <table className="artifacts-table metadata-preview-table">
                    <thead>
                      <tr>
                        {previewColumns.map((column) => (
                          <th key={column}>{column}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {previewRows.map((row, index) => (
                        <tr key={`${String(row[previewColumns[0]])}-${index}`}>
                          {previewColumns.map((column) => (
                            <td key={column}>{formatMetadataValue(row[column])}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>
        </div>
      )}

      {activeStep === 'ready' && (
        <section className="workflow-panel ready-panel">
          <CheckCircle2 size={24} />
          <div>
            <h3>{participantTableResult ? 'Data workspace is configured' : 'Finish participant import to continue'}</h3>
            <p className="muted">
              {participantTableResult
                ? `${joinPreview?.matched_subjects.length || 0} subject(s) matched. Continue to compile when the flow is valid.`
                : 'Import participant metadata and review the join preview before running the analysis.'}
            </p>
          </div>
          <button className="ghost-button" onClick={() => setActiveStep(participantTableResult ? 'join' : 'participants')}>
            Review details
          </button>
        </section>
      )}
    </div>
  );
}

function DiscoverySummary({ result }: { result: DiscoverResult }) {
  return (
    <div className="discovery-result">
      <h3>Discovery Result</h3>
      <dl>
        <dt>Dataset ID</dt>
        <dd>{result.dataset_id}</dd>
        <dt>Files Found</dt>
        <dd>{result.files}</dd>
        <dt>Subject/Session/Runs</dt>
        <dd>{result.runs}</dd>
        <dt>Metadata Tables</dt>
        <dd>{result.metadata_tables}</dd>
        <dt>Local Root</dt>
        <dd>{result.local_root}</dd>
        {result.source_url && (
          <>
            <dt>Source URL</dt>
            <dd><a href={result.source_url} target="_blank" rel="noopener noreferrer">{result.source_url}</a></dd>
          </>
        )}
      </dl>

      {result.files === 0 && (
        <div className="warning">
          No local files found. Data may need to be downloaded from the source URL or bound with a local dataset root.
        </div>
      )}
    </div>
  );
}
