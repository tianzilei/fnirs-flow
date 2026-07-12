import { useState } from 'react';
import { CheckCircle2, Package } from 'lucide-react';
import { useStore } from '../store';

const EXPORT_PROFILES = [
  {
    id: 'reproducibility_package',
    name: 'Reproducibility Package',
    description: 'Full package for reproducing analysis results',
    includes: ['plan.json', 'execution_dag.json', 'adapter_manifest.json', 'risk_register.json', 'artifact_manifest.json', 'reproducibility_manifest.json', 'data_manifest.json'],
  },
  {
    id: 'submission_package',
    name: 'Submission Package',
    description: 'Package for journal submission',
    includes: ['plan.json', 'execution_dag.json', 'reports'],
  },
  {
    id: 'reviewer_package',
    name: 'Reviewer Package',
    description: 'Package for peer review with provenance',
    includes: ['plan.json', 'execution_dag.json', 'provenance_log.json', 'reports'],
  },
];

export function ExportPackage() {
  const exportResult = useStore((s) => s.exportResult);
  const loading = useStore((s) => s.loading);
  const exportPackage = useStore((s) => s.exportPackage);
  const [exported, setExported] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedProfile, setSelectedProfile] = useState('reproducibility_package');

  const currentProfile = EXPORT_PROFILES.find((p) => p.id === selectedProfile);

  const handleExport = async () => {
    setError(null);
    try {
      await exportPackage({ profile: selectedProfile });
      setExported(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    }
  };

  return (
    <div className="page export-package work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Reproducibility</span>
          <h2>Export Package</h2>
        </div>
        <div className="page-actions">
          <button className="primary-button" onClick={handleExport} disabled={loading || exported}>
            {loading ? 'Exporting...' : exported ? 'Exported' : 'Export Package'}
          </button>
        </div>
      </section>

      <div className="export-content">
        <section className="profile-selector">
          <h3>Export Profile</h3>
          <div className="profile-cards">
            {EXPORT_PROFILES.map((profile) => (
              <div
                key={profile.id}
                role="button"
                tabIndex={0}
                className={`profile-card ${selectedProfile === profile.id ? 'selected' : ''}`}
                onClick={() => setSelectedProfile(profile.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setSelectedProfile(profile.id);
                  }
                }}
              >
                <div className="profile-card-header">
                  <Package size={18} />
                  <h4>{profile.name}</h4>
                </div>
                <p>{profile.description}</p>
              </div>
            ))}
          </div>
        </section>

        {currentProfile && (
          <section className="package-contents">
            <h3>Package Contents: {currentProfile.name}</h3>
            <ul>
              {currentProfile.includes.map((item) => (
                <li key={item}>
                  <CheckCircle2 size={14} />
                  <code>{item}</code>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="exclusion-notice">
          <h3>What's NOT Included</h3>
          <ul>
            <li>Raw data files</li>
            <li>Large intermediate files</li>
            <li>Temporary cache files</li>
          </ul>
        </section>
      </div>

      {error && (
        <div className="error-message">
          <p>Export failed: {error}</p>
        </div>
      )}

      {exported && (
        <div className="export-success">
          <div className="export-success-header">
            <CheckCircle2 size={20} />
            <p>Package exported successfully!</p>
          </div>
          {exportResult && (
            <div className="export-result-details">
              <dl>
                <div><dt>Package Path</dt><dd><code>{exportResult.package_path}</code></dd></div>
                <div><dt>Size</dt><dd>{formatBytes(exportResult.size_bytes)}</dd></div>
                <div><dt>Profile</dt><dd>{currentProfile?.name || selectedProfile}</dd></div>
              </dl>
            </div>
          )}
          <div className="export-instructions">
            <h4>Reproducibility Instructions</h4>
            <ol>
              <li>Import the package on another fnirs-flow instance</li>
              <li>Relink data to your local data directory</li>
              <li>Run the analysis</li>
            </ol>
          </div>
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}
