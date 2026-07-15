import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowLeft, CheckCircle2, Loader2, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';
import {
  AIDraftFlow,
  AIDraftScenario,
  AIDraftValidation,
  confirmProjectAIDraft,
  discardProjectAIDraft,
  formatApiError,
  generateProjectAIDraft,
  getFlow,
  getProjectAIDraft,
  validateProjectAIDraft,
} from '../api/client';

interface AIDraftReviewPanelProps {
  projectId: string;
  projectName: string;
  currentFlow: Record<string, unknown>;
  onApplied: (flow: Record<string, unknown>) => void;
  onClose: () => void;
}

const SCENARIOS: Array<{ value: AIDraftScenario; label: string }> = [
  { value: 'task', label: 'Task GLM' },
  { value: 'resting_state', label: 'Resting state' },
  { value: 'machine_learning', label: 'Machine learning' },
  { value: 'real_world', label: 'Real world' },
  { value: 'hyperscanning', label: 'Hyperscanning' },
  { value: 'multi_site', label: 'Multi-site' },
];

function recordId(item: Record<string, unknown>, index: number): string {
  return typeof item.id === 'string' ? item.id : `item-${index + 1}`;
}

function flowItems(flow: Record<string, unknown>, key: 'nodes' | 'edges'): Array<Record<string, unknown>> {
  const value = flow[key];
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object') : [];
}

function computeDiff(currentFlow: Record<string, unknown>, draft: AIDraftFlow) {
  const currentNodes = flowItems(currentFlow, 'nodes');
  const draftNodes = draft.nodes;
  const currentById = new Map(currentNodes.map((node, index) => [recordId(node, index), node]));
  const draftById = new Map(draftNodes.map((node, index) => [recordId(node, index), node]));
  const added = [...draftById.keys()].filter((id) => !currentById.has(id));
  const removed = [...currentById.keys()].filter((id) => !draftById.has(id));
  const changed = [...draftById.keys()].filter(
    (id) => currentById.has(id) && JSON.stringify(currentById.get(id)) !== JSON.stringify(draftById.get(id)),
  );
  return {
    added,
    removed,
    changed,
    currentEdges: flowItems(currentFlow, 'edges').length,
    draftEdges: draft.edges.length,
  };
}

export function AIDraftReviewPanel({
  projectId,
  projectName,
  currentFlow,
  onApplied,
  onClose,
}: AIDraftReviewPanelProps) {
  const [scenario, setScenario] = useState<AIDraftScenario>('task');
  const [studyName, setStudyName] = useState(projectName);
  const [dataFormat, setDataFormat] = useState('snirf');
  const [conditions, setConditions] = useState('');
  const [draft, setDraft] = useState<AIDraftFlow | null>(null);
  const [validation, setValidation] = useState<AIDraftValidation | null>(null);
  const [confirmedItems, setConfirmedItems] = useState<Set<string>>(new Set());
  const [reviewer, setReviewer] = useState('');
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<'apply' | 'discard' | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getProjectAIDraft(projectId)
      .then((pending) => {
        if (!active) return;
        setDraft(pending);
        const confirmed = pending?.metadata.ai_generation.confirmed_parameters ?? [];
        setConfirmedItems(new Set(confirmed));
      })
      .catch((loadError) => active && setError(formatApiError(loadError)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [projectId]);

  const ai = draft?.metadata.ai_generation;
  const required = ai?.requires_user_confirmation ?? [];
  const allConfirmed = required.every((item) => confirmedItems.has(item));
  const canApply = !!draft && allConfirmed && reviewer.trim().length > 0 && !working;
  const diff = useMemo(() => (draft ? computeDiff(currentFlow, draft) : null), [currentFlow, draft]);

  async function handleGenerate() {
    try {
      setWorking(true);
      setError(null);
      setNotice(null);
      const generated = await generateProjectAIDraft(projectId, {
        scenario,
        study_name: studyName.trim(),
        data_format: dataFormat.trim() || 'snirf',
        conditions: conditions.split(',').map((item) => item.trim()).filter(Boolean),
      });
      setDraft(generated);
      setValidation(null);
      setConfirmedItems(new Set(generated.metadata.ai_generation.confirmed_parameters ?? []));
      setNotice('Draft generated in isolation. The current flow is unchanged.');
    } catch (generateError) {
      setError(formatApiError(generateError));
    } finally {
      setWorking(false);
    }
  }

  async function handleValidate() {
    try {
      setWorking(true);
      setError(null);
      setValidation(await validateProjectAIDraft(projectId));
    } catch (validateError) {
      setError(formatApiError(validateError));
    } finally {
      setWorking(false);
    }
  }

  function toggleConfirmation(item: string) {
    setConfirmedItems((previous) => {
      const next = new Set(previous);
      if (next.has(item)) next.delete(item);
      else next.add(item);
      return next;
    });
  }

  async function handleApply() {
    if (!draft || !canApply) return;
    try {
      setWorking(true);
      setError(null);
      await confirmProjectAIDraft(projectId, [...confirmedItems], reviewer.trim());
      const applied = await getFlow(projectId);
      onApplied(applied);
      setDraft(null);
      setValidation(null);
      setConfirmAction(null);
      setNotice('Reviewed draft applied to the current flow. Validate before compiling.');
    } catch (applyError) {
      setError(formatApiError(applyError));
    } finally {
      setWorking(false);
    }
  }

  async function handleDiscard() {
    try {
      setWorking(true);
      setError(null);
      await discardProjectAIDraft(projectId);
      setDraft(null);
      setValidation(null);
      setConfirmedItems(new Set());
      setConfirmAction(null);
      setNotice('Pending AI draft discarded. The current flow was not changed.');
    } catch (discardError) {
      setError(formatApiError(discardError));
    } finally {
      setWorking(false);
    }
  }

  return (
    <aside className="ai-draft-panel" aria-label="AI Draft Review">
      <div className="ai-draft-heading">
        <button className="icon-button" onClick={onClose} aria-label="Back to validation"><ArrowLeft size={16} /></button>
        <div><span className="panel-kicker">Candidate only</span><h3>AI Draft Review</h3></div>
        <Sparkles size={18} aria-hidden="true" />
      </div>

      {loading ? <div className="panel-state"><Loader2 size={18} className="spin" /> Loading draft…</div> : null}
      {error ? <div className="ai-review-message error" role="alert"><AlertTriangle size={16} />{error}</div> : null}
      {notice ? <div className="ai-review-message success" role="status"><CheckCircle2 size={16} />{notice}</div> : null}

      {!loading && (
        <div className="ai-draft-content">
          <section className="ai-review-section">
            <h4>Generate candidate</h4>
            <label>Scenario
              <select value={scenario} onChange={(event) => setScenario(event.target.value as AIDraftScenario)}>
                {SCENARIOS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label>Study name<input value={studyName} onChange={(event) => setStudyName(event.target.value)} /></label>
            <label>Data format<input value={dataFormat} onChange={(event) => setDataFormat(event.target.value)} /></label>
            <label>Conditions (comma-separated)
              <input value={conditions} onChange={(event) => setConditions(event.target.value)} placeholder="left, right" />
            </label>
            <button className="primary-button full-width" onClick={handleGenerate} disabled={working}>
              {working ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />}
              {draft ? 'Replace pending draft' : 'Generate draft'}
            </button>
            <p className="ai-safety-note">Generation stores a pending FlowGraph only. It never runs code or overwrites the current flow.</p>
          </section>

          {draft && ai && diff ? (
            <>
              <section className="ai-review-section draft-summary">
                <div className="section-title-row"><h4>Candidate summary</h4><code>{draft.flow_id}</code></div>
                <strong>{draft.name}</strong>
                <p>{draft.description}</p>
                <div className="draft-metrics">
                  <span><strong>{draft.nodes.length}</strong> atoms</span>
                  <span><strong>{draft.edges.length}</strong> links</span>
                  <span><strong>{ai.model}</strong> model</span>
                </div>
              </section>

              <section className="ai-review-section">
                <h4>Diff from current flow</h4>
                <div className="diff-grid">
                  <span className="added">+{diff.added.length} added</span>
                  <span className="changed">~{diff.changed.length} changed</span>
                  <span className="removed">−{diff.removed.length} removed</span>
                  <span>{diff.currentEdges} → {diff.draftEdges} links</span>
                </div>
                {diff.added.length > 0 ? <p><strong>Added:</strong> {diff.added.join(', ')}</p> : null}
                {diff.removed.length > 0 ? <p><strong>Removed:</strong> {diff.removed.join(', ')}</p> : null}
                {diff.changed.length > 0 ? <p><strong>Changed:</strong> {diff.changed.join(', ')}</p> : null}
              </section>

              <section className="ai-review-section">
                <h4>Assumptions</h4>
                <ul>{ai.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
              </section>

              <section className="ai-review-section">
                <div className="section-title-row"><h4>Validation & risks</h4>
                  <button className="ghost-button compact" onClick={handleValidate} disabled={working}>Validate draft</button>
                </div>
                {!validation ? <p>Run validation to inspect schema, graph, readiness, and risk rules.</p> : (
                  <div className="draft-validation">
                    <div className={`readiness ${validation.readiness.status.toLowerCase().replace(' ', '-')}`}>
                      {validation.readiness.status} · {validation.errors.length} errors · {validation.risks.length} risks
                    </div>
                    {validation.errors.map((item) => <div className="validation-item error" key={item}>{item}</div>)}
                    {validation.warnings.map((item) => <div className="validation-item warning" key={item}>{item}</div>)}
                    {validation.risks.map((risk) => (
                      <div className={`validation-item risk ${risk.severity}`} key={risk.risk_id}>
                        <strong>{risk.code || risk.severity}</strong><span>{risk.message}</span>
                        {risk.suggested_action ? <small>{risk.suggested_action}</small> : null}
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className="ai-review-section confirmations">
                <h4>Human confirmations</h4>
                {required.length === 0 ? <p>No explicit high-impact confirmations were generated.</p> : required.map((item) => (
                  <label className="confirmation-item" key={item}>
                    <input type="checkbox" checked={confirmedItems.has(item)} onChange={() => toggleConfirmation(item)} />
                    <span>{item}</span>
                  </label>
                ))}
                <label>Reviewer
                  <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Name or email" />
                </label>
                <p className="ai-safety-note">Applying records the reviewer, timestamp, and exact confirmations. Remaining validation risks still block compile or execution.</p>
              </section>

              <div className="ai-draft-actions">
                <button className="ghost-button danger" onClick={() => setConfirmAction('discard')} disabled={working}>
                  <Trash2 size={15} />Discard
                </button>
                <button className="primary-button" onClick={() => setConfirmAction('apply')} disabled={!canApply}>
                  <ShieldCheck size={15} />Apply reviewed draft
                </button>
              </div>
            </>
          ) : null}
        </div>
      )}

      {confirmAction ? (
        <div className="ai-review-confirmation" role="alertdialog" aria-label={confirmAction === 'apply' ? 'Apply AI draft' : 'Discard AI draft'}>
          <strong>{confirmAction === 'apply' ? 'Replace the current flow?' : 'Discard the pending draft?'}</strong>
          <p>{confirmAction === 'apply'
            ? 'The reviewed candidate will become the editable current flow. It will not execute automatically.'
            : 'The candidate will be removed; the current flow stays unchanged.'}</p>
          <div>
            <button className={confirmAction === 'apply' ? 'primary-button' : 'ghost-button danger'} onClick={confirmAction === 'apply' ? handleApply : handleDiscard} disabled={working}>
              {working ? 'Working…' : confirmAction === 'apply' ? 'Confirm apply' : 'Confirm discard'}
            </button>
            <button className="ghost-button" onClick={() => setConfirmAction(null)} disabled={working}>Cancel</button>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
