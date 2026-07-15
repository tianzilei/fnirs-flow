import { useState } from 'react';
import {
  AlertTriangle, CheckCircle2, GitFork,
  Package, ShieldCheck, Upload
} from 'lucide-react';
import { useStore } from '../store';

export function ImportPackage() {
  const importStatus = useStore((s) => s.importStatus);
  const loading = useStore((s) => s.loading);
  const project = useStore((s) => s.project);
  const importPackage = useStore((s) => s.importPackage);
  const fork = useStore((s) => s.fork);
  const trustAtom = useStore((s) => s.trustAtom);
  const relinkData = useStore((s) => s.relinkData);

  const [packagePath, setPackagePath] = useState('');
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [importSuccess, setImportSuccess] = useState(false);
  const [dataRoot, setDataRoot] = useState('');

  const handleImport = async () => {
    if (!packagePath.trim() || !project) return;
    setImporting(true);
    setError(null);
    try {
      await importPackage(project.id, packagePath.trim());
      setImportSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="page import-package work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Reproducibility</span>
          <h2>Import Package</h2>
        </div>
      </section>

      <div className="import-content">
        <section className="import-form workflow-panel">
          <div className="section-heading">
            <div>
              <h3>Import .fnirsflow.zip Package</h3>
              <p className="muted">Load a reproducibility package, then review trust and data relinking steps.</p>
            </div>
          </div>
          <div className="form-group">
            <label htmlFor="package-path">Package Path</label>
            <div className="input-with-button">
              <input
                id="package-path"
                type="text"
                value={packagePath}
                onChange={(e) => setPackagePath(e.target.value)}
                placeholder="/path/to/package.fnirsflow.zip"
                disabled={importing || importStatus?.imported}
              />
              <button
                className="primary-button"
                onClick={handleImport}
                disabled={!packagePath.trim() || importing || importStatus?.imported}
              >
                {importing ? (
                  <>Importing...</>
                ) : (
                  <>
                    <Upload size={16} />
                    Import
                  </>
                )}
              </button>
            </div>
          </div>
          {error && (
            <div className="error-message">
              <AlertTriangle size={16} />
              <span>{error}</span>
            </div>
          )}
        </section>

        {importStatus?.imported && (
          <>
            <section className="import-status">
              <div className={`status-banner ${importStatus.read_only ? 'read-only' : 'editable'}`}>
                {importStatus.read_only ? (
                  <>
                    <AlertTriangle size={18} />
                    <div>
                      <strong>Read-Only Package</strong>
                      <span>This package is imported as read-only. Fork to make edits.</span>
                    </div>
                  </>
                ) : (
                  <>
                    <CheckCircle2 size={18} />
                    <div>
                      <strong>Editable Package</strong>
                      <span>This package is imported and can be edited directly.</span>
                    </div>
                  </>
                )}
              </div>

              {importStatus.read_only && (
                <div className="fork-action">
                  <button className="ghost-button" onClick={fork} disabled={loading}>
                    <GitFork size={16} />
                    <span>Fork to Editable Copy</span>
                  </button>
                  <p className="help-text">
                    Forking creates a new editable project based on this imported package.
                  </p>
                </div>
              )}
            </section>

            <section className="import-form">
              <h3>Relink Local Data</h3>
              <div className="form-group">
                <label htmlFor="data-root">Data Root</label>
                <div className="input-with-button">
                  <input
                    id="data-root"
                    type="text"
                    value={dataRoot}
                    onChange={(event) => setDataRoot(event.target.value)}
                    placeholder="/path/to/local/dataset"
                    disabled={loading}
                  />
                  <button
                    className="primary-button"
                    onClick={() => relinkData(dataRoot.trim())}
                    disabled={!dataRoot.trim() || loading}
                  >
                    Relink
                  </button>
                </div>
                {importStatus.relinked && <p className="help-text">Linked to {importStatus.data_root}</p>}
              </div>
            </section>

            {importStatus.quarantined_atoms.length > 0 && (
              <section className="quarantine-section">
                <h3>
                  <ShieldCheck size={18} />
                  Quarantined Atoms
                </h3>
                <p className="help-text">
                  The following atoms are quarantined because they are custom or untrusted.
                  Review and trust each atom individually before execution.
                </p>
                <div className="quarantine-list">
                  {importStatus.quarantined_atoms.map((atomId) => (
                    <div key={atomId} className="quarantine-item">
                      <div className="quarantine-info">
                        <Package size={16} />
                        <code>{atomId}</code>
                      </div>
                      <button
                        className="ghost-button small"
                        onClick={() => trustAtom(atomId)}
                        disabled={loading}
                      >
                        <ShieldCheck size={14} />
                        Trust
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}

        {!importStatus?.imported && !importSuccess && (
          <section className="import-help workflow-panel">
            <h3>How to Import</h3>
            <ol>
              <li>Obtain a <code>.fnirsflow.zip</code> package from another user or your own export</li>
              <li>Enter the full path to the package file above</li>
              <li>Click "Import" to load the package</li>
              <li>Review any quarantined atoms and trust them if safe</li>
              <li>Fork the project if you need to make edits</li>
            </ol>
          </section>
        )}
      </div>
    </div>
  );
}
