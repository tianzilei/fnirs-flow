import { useState } from 'react';
import type { DiscoverResult } from '../api/client';

interface Dataset {
  id: string;
  name: string;
  description: string;
}

interface DataImportProps {
  onDiscover: (datasetId: string) => Promise<DiscoverResult>;
  datasets?: Dataset[];
}

const DEFAULT_DATASETS: Dataset[] = [
  { id: 'mne-fnirs-motor', name: 'MNE fNIRS Motor Task', description: 'Finger tapping experiment' },
];

export function DataImport({ onDiscover, datasets = DEFAULT_DATASETS }: DataImportProps) {
  const [selectedDataset, setSelectedDataset] = useState('');
  const [result, setResult] = useState<DiscoverResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleDiscover = async () => {
    if (!selectedDataset) return;

    setLoading(true);
    setError('');
    try {
      const res = await onDiscover(selectedDataset);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Discovery failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page data-import work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Dataset</span>
          <h2>Data Import</h2>
        </div>
        <div className="page-actions">
          <button className="primary-button" onClick={handleDiscover} disabled={!selectedDataset || loading}>
            {loading ? 'Discovering...' : 'Discover Dataset'}
          </button>
        </div>
      </section>

      <div className="dataset-selector">
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
            </div>
          ))}
        </div>

      </div>

      {error && <div className="error-message">{error}</div>}

      {result && (
        <div className="discovery-result">
          <h3>Discovery Result</h3>
          <dl>
            <dt>Dataset ID</dt>
            <dd>{result.dataset_id}</dd>
            <dt>Files Found</dt>
            <dd>{result.files}</dd>
            <dt>Subject/Session/Runs</dt>
            <dd>{result.runs}</dd>
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
              No local files found. Data may need to be downloaded from the source URL.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
