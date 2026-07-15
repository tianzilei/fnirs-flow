import { useEffect, useState } from 'react';
import {
  BranchInfo,
  createDesignBranch,
  createDesignCommit,
  deleteDesignBranch,
  checkoutDesignBranch,
  DesignCommitLogEntry,
  DesignHistoryStatus,
  formatApiError,
  getDesignDiff,
  getDesignHistory,
  initializeDesignHistory,
  listDesignCommits,
  DiffResult,
} from '../api/client';

interface DesignHistoryPanelProps {
  projectId: string;
  onFlowChanged?: () => void | Promise<void>;
}

export function DesignHistoryPanel({ projectId, onFlowChanged }: DesignHistoryPanelProps) {
  const [status, setStatus] = useState<DesignHistoryStatus | null>(null);
  const [commits, setCommits] = useState<DesignCommitLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Commit dialog
  const [showCommitDialog, setShowCommitDialog] = useState(false);
  const [commitMessage, setCommitMessage] = useState('');
  const [committing, setCommitting] = useState(false);

  // Branch dialog
  const [showBranchDialog, setShowBranchDialog] = useState(false);
  const [branchName, setBranchName] = useState('');
  const [creatingBranch, setCreatingBranch] = useState(false);

  // Diff
  const [diffResult, setDiffResult] = useState<DiffResult | null>(null);
  const [diffFrom, setDiffFrom] = useState<string | null>(null);
  const [diffTo, setDiffTo] = useState<string | null>(null);

  useEffect(() => {
    loadHistory();
  }, [projectId]);

  async function loadHistory() {
    try {
      setLoading(true);
      setError(null);
      const data = await getDesignHistory(projectId);
      setStatus(data);
      if (data.head) {
        const log = await listDesignCommits(projectId);
        setCommits(log);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load design history');
    } finally {
      setLoading(false);
    }
  }

  async function handleInitialize() {
    try {
      setError(null);
      await initializeDesignHistory(projectId);
      setSuccess('Design history initialized');
      await loadHistory();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function handleCommit() {
    if (!commitMessage.trim()) return;
    try {
      setCommitting(true);
      setError(null);
      setSuccess(null);
      await createDesignCommit(projectId, commitMessage);
      setShowCommitDialog(false);
      setCommitMessage('');
      setSuccess('Design committed');
      await loadHistory();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setCommitting(false);
    }
  }

  async function handleCreateBranch() {
    if (!branchName.trim()) return;
    try {
      setCreatingBranch(true);
      setError(null);
      setSuccess(null);
      await createDesignBranch(projectId, branchName);
      setShowBranchDialog(false);
      setBranchName('');
      setSuccess(`Branch "${branchName}" created`);
      await loadHistory();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setCreatingBranch(false);
    }
  }

  async function handleCheckout(target: string) {
    try {
      setError(null);
      setSuccess(null);
      await checkoutDesignBranch(projectId, target);
      setSuccess(`Switched to ${target}`);
      await loadHistory();
      await onFlowChanged?.();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function handleDeleteBranch(name: string) {
    try {
      setError(null);
      setSuccess(null);
      await deleteDesignBranch(projectId, name);
      setSuccess(`Branch "${name}" deleted`);
      await loadHistory();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function handleDiff(fromId: string, toId: string) {
    try {
      setError(null);
      const result = await getDesignDiff(projectId, fromId, toId);
      setDiffResult(result);
      setDiffFrom(fromId);
      setDiffTo(toId);
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  function shortHash(hash: string) {
    return hash.slice(0, 8);
  }

  if (loading) {
    return (
      <div className="version-history-panel">
        <h3>Design History</h3>
        <div className="loading">Loading...</div>
      </div>
    );
  }

  // Not initialized yet
  if (!status?.head) {
    return (
      <div className="version-history-panel">
        <h3>Design History</h3>
        <div className="empty">
          <p>Design history not initialized</p>
          <button className="ghost-button small" onClick={handleInitialize}>
            Initialize
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="version-history-panel">
      <div className="version-history-heading">
        <h3>Design History</h3>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="ghost-button small" onClick={loadHistory}>Refresh</button>
          <button className="ghost-button small" onClick={() => setShowCommitDialog(true)}>
            Commit
          </button>
          <button className="ghost-button small" onClick={() => setShowBranchDialog(true)}>
            Branch
          </button>
        </div>
      </div>

      {success && <div className="version-success" role="status">{success}</div>}
      {error && <div className="error" role="alert">{error}</div>}

      {/* HEAD & Branch info */}
      <div style={{ marginBottom: '0.75rem', fontSize: '0.85rem' }}>
        <div>
          <strong>Branch:</strong>{' '}
          {status.branches.find((b: BranchInfo) => b.is_current)?.name || '(detached)'}
          {status.dirty && <span className="badge" style={{ marginLeft: '0.5rem' }}>dirty</span>}
        </div>
        <div>
          <strong>HEAD:</strong> {shortHash(status.head.commit_id)}
          {status.head.message && ` — ${status.head.message}`}
        </div>
      </div>

      {/* Branches */}
      {status.branches.length > 1 && (
        <div style={{ marginBottom: '0.75rem' }}>
          <strong>Branches:</strong>{' '}
          {status.branches.map((b: BranchInfo) => (
            <span key={b.name} style={{ marginRight: '0.5rem' }}>
              <button
                className={`ghost-button small ${b.is_current ? '' : ''}`}
                onClick={() => !b.is_current && handleCheckout(b.name)}
                disabled={b.is_current}
                style={{ fontWeight: b.is_current ? 'bold' : 'normal' }}
              >
                {b.name}
              </button>
              {!b.is_current && (
                <button
                  className="ghost-button small"
                  onClick={() => handleDeleteBranch(b.name)}
                  title={`Delete branch ${b.name}`}
                  style={{ padding: '0 0.25rem', fontSize: '0.75rem' }}
                >
                  x
                </button>
              )}
            </span>
          ))}
        </div>
      )}

      {/* Commit list */}
      {commits.length === 0 ? (
        <div className="empty">No commits yet</div>
      ) : (
        <div className="version-list">
          {commits.map((commit: DesignCommitLogEntry, idx: number) => (
            <div key={commit.commit_id} className="version-entry">
              <div className="version-header">
                <span className="revision">{shortHash(commit.commit_id)}</span>
                {idx === 0 && <span className="badge">HEAD</span>}
              </div>
              <div className="version-details">
                <div className="reason">{commit.message || '(no message)'}</div>
                <div className="timestamp">
                  {commit.author.display_name} &middot;{' '}
                  {new Date(commit.created_at).toLocaleString()}
                </div>
                {commit.parents.length > 0 && (
                  <div style={{ fontSize: '0.75rem', opacity: 0.7 }}>
                    parent: {shortHash(commit.parents[0])}
                  </div>
                )}
              </div>
              {/* Diff with previous commit */}
              {idx < commits.length - 1 && (
                <button
                  className="ghost-button small"
                  onClick={() => handleDiff(commits[idx + 1].commit_id, commit.commit_id)}
                  style={{ marginTop: '0.25rem' }}
                >
                  Diff
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Diff panel */}
      {diffResult && diffFrom && diffTo && (
        <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'var(--surface-1, #f5f5f5)', borderRadius: '0.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
            <strong>Diff: {shortHash(diffFrom)}..{shortHash(diffTo)}</strong>
            <button className="ghost-button small" onClick={() => setDiffResult(null)}>Close</button>
          </div>
          {diffResult.changes.length === 0 ? (
            <div className="empty">No changes</div>
          ) : (
            <div style={{ fontSize: '0.8rem' }}>
              {diffResult.changes.map((ch, i) => (
                <div key={i} style={{ padding: '0.25rem 0', borderBottom: '1px solid var(--border, #ddd)' }}>
                  <span style={{ fontWeight: 'bold' }}>{ch.kind}</span>
                  {ch.node_id && <span> node:{ch.node_id}</span>}
                  {ch.edge_id && <span> edge:{ch.edge_id}</span>}
                  {ch.path && <span> .{ch.path}</span>}
                  {ch.before !== undefined && (
                    <span style={{ color: 'var(--error, #d32f2f)' }}> {JSON.stringify(ch.before)}</span>
                  )}
                  {ch.after !== undefined && (
                    <span style={{ color: 'var(--success, #388e3c)' }}> {JSON.stringify(ch.after)}</span>
                  )}
                </div>
              ))}
            </div>
          )}
          {diffResult.from_flow_hash !== diffResult.to_flow_hash && (
            <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', opacity: 0.7 }}>
              flow_hash: {shortHash(diffResult.from_flow_hash)} → {shortHash(diffResult.to_flow_hash)}
            </div>
          )}
        </div>
      )}

      {/* Commit dialog */}
      {showCommitDialog && (
        <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'var(--surface-1, #f5f5f5)', borderRadius: '0.5rem' }}>
          <strong>Save Design Version</strong>
          <input
            type="text"
            value={commitMessage}
            onChange={(e) => setCommitMessage(e.target.value)}
            placeholder="Commit message"
            style={{ width: '100%', margin: '0.5rem 0', padding: '0.5rem' }}
            onKeyDown={(e) => e.key === 'Enter' && handleCommit()}
          />
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="ghost-button small" onClick={handleCommit} disabled={committing || !commitMessage.trim()}>
              {committing ? 'Committing...' : 'Commit'}
            </button>
            <button className="ghost-button small" onClick={() => { setShowCommitDialog(false); setCommitMessage(''); }} disabled={committing}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Branch dialog */}
      {showBranchDialog && (
        <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'var(--surface-1, #f5f5f5)', borderRadius: '0.5rem' }}>
          <strong>Create Branch</strong>
          <input
            type="text"
            value={branchName}
            onChange={(e) => setBranchName(e.target.value)}
            placeholder="Branch name (e.g. feature/short-channel)"
            style={{ width: '100%', margin: '0.5rem 0', padding: '0.5rem' }}
            onKeyDown={(e) => e.key === 'Enter' && handleCreateBranch()}
          />
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="ghost-button small" onClick={handleCreateBranch} disabled={creatingBranch || !branchName.trim()}>
              {creatingBranch ? 'Creating...' : 'Create'}
            </button>
            <button className="ghost-button small" onClick={() => { setShowBranchDialog(false); setBranchName(''); }} disabled={creatingBranch}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
