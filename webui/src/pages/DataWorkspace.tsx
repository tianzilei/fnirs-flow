import { useState } from 'react';
import { useStore } from '../store';

interface Dataset {
  id: string;
  name: string;
  description: string;
}

const DEFAULT_DATASETS: Dataset[] = [
  { id: 'mne-fnirs-motor', name: 'MNE fNIRS Motor Task', description: 'Finger tapping experiment' },
];

export function DataWorkspace() {
  const discover = useStore((s) => s.discover);
  const discoverResult = useStore((s) => s.discoverResult);
  const [selectedDataset, setSelectedDataset] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleDiscover = async () => {
    if (!selectedDataset) return;
    setLoading(true);
    setError('');
    try {
      await discover(selectedDataset);
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
          <h2>Data Workspace</h2>
        </div>
        <div className="page-actions">
          <button className="primary-button" onClick={handleDiscover} disabled={!selectedDataset || loading}>
            {loading ? 'Discovering...' : 'Discover Dataset'}
          </button>
        </div>
      </section>

      <div className="dataset-selector">
        <div className="dataset-list">
          {DEFAULT_DATASETS.map((ds) => (
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

      {discoverResult && (
        <div className="discovery-result">
          <h3>Discovery Result</h3>
          <dl>
            <dt>Dataset ID</dt>
            <dd>{discoverResult.dataset_id}</dd>
            <dt>Files Found</dt>
            <dd>{discoverResult.files}</dd>
            <dt>Subject/Session/Runs</dt>
            <dd>{discoverResult.runs}</dd>
            <dt>Local Root</dt>
            <dd>{discoverResult.local_root}</dd>
            {discoverResult.source_url && (
              <>
                <dt>Source URL</dt>
                <dd><a href={discoverResult.source_url} target="_blank" rel="noopener noreferrer">{discoverResult.source_url}</a></dd>
              </>
            )}
          </dl>

          {discoverResult.files === 0 && (
            <div className="warning">
              No local files found. Data may need to be downloaded from the source URL.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
