import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ArrowLeft, CheckCircle2, ChevronDown, ChevronRight, Loader2, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';
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
import { useModalDialog } from '../utils/useModalDialog';

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
];

const DEFAULT_AI_BASE_URL = 'https://api.openai.com/v1';
const DEFAULT_AI_MODEL = 'gpt-5-mini';
const DEFAULT_AI_TEMPERATURE = 0.1;
const DEFAULT_AI_MAX_TOKENS = 12000;
const DEFAULT_AI_TIMEOUT_SECONDS = 120;
const DRAFT_STEPS = [
  { id: 'generate', label: 'Generate' },
  { id: 'validate', label: 'Validate' },
  { id: 'review', label: 'Review' },
  { id: 'apply', label: 'Apply' },
] as const;

type DraftStep = typeof DRAFT_STEPS[number]['id'];

function recordId(item: Record<string, unknown>, index: number): string {
  return typeof item.id === 'string' ? item.id : `item-${index + 1}`;
}

function flowItems(flow: Record<string, unknown>, key: 'flow_atoms' | 'edges'): Array<Record<string, unknown>> {
  const value = flow[key];
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object') : [];
}

function computeDiff(currentFlow: Record<string, unknown>, draft: AIDraftFlow) {
  const currentNodes = flowItems(currentFlow, 'flow_atoms');
  const draftNodes = draft.flow_atoms;
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
  const [aiSettingsOpen, setAiSettingsOpen] = useState(false);
  const [aiMode, setAiMode] = useState<'template' | 'openai-compatible'>('template');
  const [aiProvider, setAiProvider] = useState('OpenAI compatible');
  const [aiBaseUrl, setAiBaseUrl] = useState(DEFAULT_AI_BASE_URL);
  const [aiModel, setAiModel] = useState(DEFAULT_AI_MODEL);
  const [aiOrganization, setAiOrganization] = useState('');
  const [aiProject, setAiProject] = useState('');
  const [aiTemperature, setAiTemperature] = useState(DEFAULT_AI_TEMPERATURE);
  const [aiMaxTokens, setAiMaxTokens] = useState(DEFAULT_AI_MAX_TOKENS);
  const [aiTimeoutSeconds, setAiTimeoutSeconds] = useState(DEFAULT_AI_TIMEOUT_SECONDS);
  const [draft, setDraft] = useState<AIDraftFlow | null>(null);
  const [validation, setValidation] = useState<AIDraftValidation | null>(null);
  const [confirmedItems, setConfirmedItems] = useState<Set<string>>(new Set());
  const [reviewer, setReviewer] = useState('');
  const [draftStep, setDraftStep] = useState<DraftStep>('generate');
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<'apply' | 'discard' | null>(null);
  const applyTriggerRef = useRef<HTMLButtonElement>(null);
  const discardTriggerRef = useRef<HTMLButtonElement>(null);
  const closeConfirmation = useCallback(() => {
    const trigger = confirmAction === 'apply' ? applyTriggerRef.current : discardTriggerRef.current;
    setConfirmAction(null);
    requestAnimationFrame(() => trigger?.focus());
  }, [confirmAction]);
  const confirmationRef = useModalDialog(confirmAction !== null, closeConfirmation);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getProjectAIDraft(projectId)
      .then((pending) => {
        if (!active) return;
        setDraft(pending);
        const confirmed = pending?.metadata.ai_generation.confirmed_parameters ?? [];
        setConfirmedItems(new Set(confirmed));
        if (pending) setDraftStep('validate');
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
        ai_settings: {
          mode: aiMode,
          provider: aiProvider.trim() || 'OpenAI compatible',
          base_url: aiBaseUrl.trim() || DEFAULT_AI_BASE_URL,
          model: aiModel.trim() || DEFAULT_AI_MODEL,
          organization: aiOrganization.trim() || undefined,
          project: aiProject.trim() || undefined,
          temperature: aiTemperature,
          max_tokens: aiMaxTokens,
          timeout_seconds: aiTimeoutSeconds,
        },
      });
      setDraft(generated);
      setValidation(null);
      setConfirmedItems(new Set(generated.metadata.ai_generation.confirmed_parameters ?? []));
      setDraftStep('validate');
      if (generated.metadata.ai_generation.settings?.direct_import) {
        onApplied(await getFlow(projectId));
        setNotice('External API generated a FlowGraph and imported it into the current flow. Confirm its AI status before execution.');
      } else {
        setNotice('Draft generated in isolation. The current flow is unchanged.');
      }
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
      setDraftStep('validate');
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
      setDraftStep('generate');
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
      setDraftStep('generate');
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
          <div className="workflow-stepper ai-stepper">
            {DRAFT_STEPS.map((step, index) => {
              const done = (
                (step.id === 'generate' && !!draft)
                || (step.id === 'validate' && !!validation)
                || (step.id === 'review' && allConfirmed)
                || (step.id === 'apply' && canApply)
              );
              return (
                <button
                  key={step.id}
                  className={`${draftStep === step.id ? 'active' : ''} ${done ? 'done' : ''}`}
                  onClick={() => setDraftStep(step.id)}
                  disabled={step.id !== 'generate' && !draft}
                >
                  {done ? <CheckCircle2 size={14} /> : <span>{index + 1}</span>}
                  {step.label}
                </button>
              );
            })}
          </div>

          {draftStep === 'generate' && (
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
            <div className="ai-settings-subpanel">
              <button
                type="button"
                className="ai-settings-toggle"
                onClick={() => setAiSettingsOpen((open) => !open)}
                aria-expanded={aiSettingsOpen}
              >
                <span>{aiSettingsOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
                <strong>AI API settings</strong>
                <em>{aiMode === 'template' ? 'Template mode' : aiModel || 'OpenAI-compatible'}</em>
              </button>
              {aiSettingsOpen && (
                <div className="ai-settings-grid">
                  <label>Mode
                    <select value={aiMode} onChange={(event) => setAiMode(event.target.value as 'template' | 'openai-compatible')}>
                      <option value="template">Template mode</option>
                      <option value="openai-compatible">OpenAI-compatible</option>
                    </select>
                  </label>
                  <label>Provider
                    <input value={aiProvider} onChange={(event) => setAiProvider(event.target.value)} placeholder="OpenAI compatible" />
                  </label>
                  <label className="span-2">Base URL
                    <input value={aiBaseUrl} onChange={(event) => setAiBaseUrl(event.target.value)} placeholder="https://api.openai.com/v1" />
                  </label>
                  <label>Model
                    <input value={aiModel} onChange={(event) => setAiModel(event.target.value)} placeholder={DEFAULT_AI_MODEL} />
                  </label>
                  <label>Temperature
                    <input
                      value={aiTemperature}
                      onChange={(event) => setAiTemperature(Number(event.target.value))}
                      type="number"
                      min="0"
                      max="2"
                      step="0.1"
                    />
                  </label>
                  <label>Max tokens
                    <input
                      value={aiMaxTokens}
                      onChange={(event) => setAiMaxTokens(Number(event.target.value))}
                      type="number"
                      min="1"
                      step="1"
                    />
                  </label>
                  <label>Timeout seconds
                    <input
                      value={aiTimeoutSeconds}
                      onChange={(event) => setAiTimeoutSeconds(Number(event.target.value))}
                      type="number"
                      min="1"
                      step="1"
                    />
                  </label>
                  <label>Organization
                    <input value={aiOrganization} onChange={(event) => setAiOrganization(event.target.value)} placeholder="optional" />
                  </label>
                  <label>Project
                    <input value={aiProject} onChange={(event) => setAiProject(event.target.value)} placeholder="optional" />
                  </label>
                  <p className="ai-safety-note span-2">OpenAI-compatible mode uses server-side environment variables for credentials. The browser never accepts or stores the API key.</p>
                </div>
              )}
            </div>
            <button className="primary-button full-width" onClick={handleGenerate} disabled={working}>
              {working ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />}
              {draft ? 'Replace pending draft' : 'Generate draft'}
            </button>
            <p className="ai-safety-note">Generation stores a pending FlowGraph only. It never runs code or overwrites the current flow.</p>
          </section>
          )}

          {draft && ai && diff ? (
            <>
              {draftStep === 'validate' && (
              <section className="ai-review-section draft-summary">
                <div className="section-title-row"><h4>Candidate summary</h4><code>{draft.flow_id}</code></div>
                <strong>{draft.name}</strong>
                <p>{draft.description}</p>
                <div className="draft-metrics">
                  <span><strong>{draft.flow_atoms.length}</strong> atoms</span>
                  <span><strong>{draft.edges.length}</strong> links</span>
                  <span><strong>{ai.model}</strong> model</span>
                </div>
              </section>
              )}

              {draftStep === 'review' && (
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
              )}

              {draftStep === 'review' && (
              <section className="ai-review-section">
                <h4>Assumptions</h4>
                <ul>{ai.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
              </section>
              )}

              {draftStep === 'validate' && (
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
              )}

              {draftStep === 'review' && (
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
              )}

              {draftStep === 'apply' && (
              <section className="ai-review-section">
                <h4>Apply reviewed draft</h4>
                <p>{canApply ? 'All required confirmations are complete.' : 'Complete every confirmation and reviewer field before applying.'}</p>
                <div className="draft-metrics">
                  <span><strong>{draft.flow_atoms.length}</strong> atoms</span>
                  <span><strong>{draft.edges.length}</strong> links</span>
                  <span><strong>{confirmedItems.size}/{required.length}</strong> confirmations</span>
                </div>
              </section>
              )}

              <div className="ai-draft-actions">
                <button ref={discardTriggerRef} className="ghost-button danger" onClick={() => setConfirmAction('discard')} disabled={working}>
                  <Trash2 size={15} />Discard
                </button>
                <button ref={applyTriggerRef} className="primary-button" onClick={() => setConfirmAction('apply')} disabled={!canApply}>
                  <ShieldCheck size={15} />Apply reviewed draft
                </button>
              </div>
            </>
          ) : null}
        </div>
      )}

      {confirmAction ? (
        <div
          ref={confirmationRef}
          className="ai-review-confirmation"
          role="alertdialog"
          aria-modal="true"
          aria-label={confirmAction === 'apply' ? 'Apply AI draft' : 'Discard AI draft'}
          aria-describedby="ai-draft-confirmation-description"
          tabIndex={-1}
        >
          <strong>{confirmAction === 'apply' ? 'Replace the current flow?' : 'Discard the pending draft?'}</strong>
          <p id="ai-draft-confirmation-description">{confirmAction === 'apply'
            ? 'The reviewed candidate will become the editable current flow. It will not execute automatically.'
            : 'The candidate will be removed; the current flow stays unchanged.'}</p>
          <div>
            <button className={confirmAction === 'apply' ? 'primary-button' : 'ghost-button danger'} onClick={confirmAction === 'apply' ? handleApply : handleDiscard} disabled={working}>
              {working ? 'Working…' : confirmAction === 'apply' ? 'Confirm apply' : 'Confirm discard'}
            </button>
            <button className="ghost-button" onClick={closeConfirmation} disabled={working}>Cancel</button>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
