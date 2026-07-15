import { useEffect, useState } from 'react';
import {
  formatApiError,
  getVersionHistory,
  Project,
  restoreProjectRevision,
  VersionHistoryEntry,
} from '../api/client';

interface BundleRecoveryPanelProps {
  projectId: string;
  onRestored?: (project: Project) => void | Promise<void>;
}

export function BundleRecoveryPanel({ projectId, onRestored }: BundleRecoveryPanelProps) {
  const [history, setHistory] = useState<VersionHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingRevision, setPendingRevision] = useState<number | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    loadHistory();
  }, [projectId]);

  async function loadHistory() {
    try {
      setLoading(true);
      setError(null);
      const data = await getVersionHistory(projectId);
      setHistory(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load version history');
    } finally {
      setLoading(false);
    }
  }

  async function handleRestore() {
    if (pendingRevision === null) return;
    const revision = pendingRevision;
    try {
      setRestoring(true);
      setError(null);
      setSuccess(null);
      const restored = await restoreProjectRevision(projectId, revision);
      setPendingRevision(null);
      setSuccess(`Revision ${revision} restored as revision ${restored.revision}.`);
      await loadHistory();
      await onRestored?.(restored);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setRestoring(false);
    }
  }

  if (loading) {
    return (
      <div className="version-history-panel">
        <h3>Bundle Recovery</h3>
        <div className="loading">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="version-history-panel">
        <h3>Bundle Recovery</h3>
        <div className="error" role="alert">{error}</div>
        <button className="ghost-button small" onClick={loadHistory}>Retry</button>
      </div>
    );
  }

  return (
    <div className="version-history-panel">
      <div className="version-history-heading">
        <h3>Bundle Recovery</h3>
        <button className="ghost-button small" onClick={loadHistory} disabled={restoring}>
          Refresh
        </button>
      </div>
      {success && <div className="version-success" role="status">{success}</div>}
      {history.length === 0 ? (
        <div className="empty">No version history available</div>
      ) : (
        <div className="version-list">
          {history.map((entry) => (
            <div
              key={entry.revision}
              className={`version-entry ${entry.current ? 'current' : ''}`}
            >
              <div className="version-header">
                <span className="revision">Revision {entry.revision}</span>
                {entry.current && <span className="badge">Current</span>}
              </div>
              <div className="version-details">
                <div className="reason">{entry.reason}</div>
                <div className="timestamp">
                  {new Date(entry.saved_at).toLocaleString()}
                </div>
              </div>
              {!entry.current && pendingRevision !== entry.revision && (
                <button
                  className="restore-button"
                  onClick={() => {
                    setPendingRevision(entry.revision);
                    setSuccess(null);
                  }}
                  disabled={restoring}
                >
                  Restore
                </button>
              )}
              {pendingRevision === entry.revision && (
                <div className="restore-confirmation" role="alertdialog" aria-label={`Restore revision ${entry.revision}`}>
                  <p>This restores revision {entry.revision} as a new project revision. Continue?</p>
                  <div className="restore-confirmation-actions">
                    <button className="restore-button" onClick={handleRestore} disabled={restoring}>
                      {restoring ? 'Restoring...' : 'Confirm restore'}
                    </button>
                    <button className="ghost-button small" onClick={() => setPendingRevision(null)} disabled={restoring}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Backward-compatible alias
export { BundleRecoveryPanel as VersionHistoryPanel };
