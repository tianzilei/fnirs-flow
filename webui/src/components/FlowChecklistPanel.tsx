import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Check, Circle, Forward, Link2, ListChecks, Plus, SkipForward } from 'lucide-react';
import {
  getFlowChecklist,
  listFlowChecklists,
  listAtomTemplates,
  listEmptyMarkerSpecs,
  type AtomTemplate,
  type EmptyMarkerSpec,
  type FlowChecklist,
  type FlowChecklistSummary,
  type FlowChecklistStep,
} from '../api/client';
import {
  addEmptyMarkerForCategory,
  addTemplateAtomToFlow,
  atomCollectionKey,
  buildChecklistMissingSequence,
  checklistTemplateRecommendations,
  checklistStepTemplateIds,
  connectSkipReasonText,
  connectAtomRequiredInputsWithReport,
  connectChecklistAtomsWithReport,
  firstChecklistStepAtom,
  findChecklistStepTemplate,
  flowAtoms,
  generateChecklistReport,
  getAtomInputStatuses,
  getChecklistChoices,
  getChecklistMetadata,
  inferChecklistScenario,
  withChecklistChoice,
  withChecklistMetadata,
  withOrderPolicy,
} from '../flow/atomFactory';

interface FlowChecklistPanelProps {
  flow: Record<string, unknown>;
  onChange: (flow: Record<string, unknown>) => void;
  onFocusAtom?: (atomId: string) => void;
  onActiveStepChange?: (step: {
    scenarioId: string;
    slotId: string;
    label: string;
    templateIds: string[];
    recommendations: ReturnType<typeof checklistTemplateRecommendations>;
  } | null) => void;
  focusedSlotId?: string | null;
  readOnly?: boolean;
}

type StepStatus = 'complete' | 'skipped' | 'needs_link' | 'blocked' | 'missing' | 'optional';

interface StepState {
  status: StepStatus;
  atom?: Record<string, unknown>;
  missingInputs: string[];
  inputStatuses: ReturnType<typeof getAtomInputStatuses>;
  blockedBy: string[];
}

const SKIP_REASON_OPTIONS = [
  { value: 'reviewed_empty_processing', label: 'Reviewed no-op' },
  { value: 'method_not_needed', label: 'Method not needed' },
  { value: 'data_not_available', label: 'Data unavailable' },
  { value: 'custom', label: 'Custom reason' },
];

function stepSkipped(atoms: Array<Record<string, unknown>>, step: FlowChecklistStep) {
  if (!step.allow_empty_marker) return false;
  return atoms.some((atom) => {
    const metadata = (atom.metadata as Record<string, unknown>) || {};
    return (
      (atom.operation === 'empty_marker' || atom.atom_type === 'empty_marker' || metadata.empty_atom === true) &&
      metadata.skipped_processing_category === step.category
    );
  });
}

function missingRequiredInputs(flow: Record<string, unknown>, atom: Record<string, unknown> | undefined) {
  if (!atom) return [];
  return getAtomInputStatuses(flow, atom)
    .filter((port) => port.required && !port.connected)
    .map((port) => port.schema);
}

function statusForStep(
  flow: Record<string, unknown>,
  step: FlowChecklistStep,
  atoms: Array<Record<string, unknown>>,
  completedSlots: Set<string>
): StepState {
  const atom = firstChecklistStepAtom(atoms, step);
  if (atom) {
    const inputStatuses = getAtomInputStatuses(flow, atom);
    const missingInputs = missingRequiredInputs(flow, atom);
    return {
      status: missingInputs.length > 0 ? 'needs_link' : 'complete',
      atom,
      missingInputs,
      inputStatuses,
      blockedBy: [],
    };
  }
  if (stepSkipped(atoms, step)) return { status: 'skipped', missingInputs: [], inputStatuses: [], blockedBy: [] };
  const blockedBy = step.depends_on.filter((slot) => !completedSlots.has(slot));
  if (blockedBy.length > 0) return { status: 'blocked', missingInputs: [], inputStatuses: [], blockedBy };
  return { status: step.required ? 'missing' : 'optional', missingInputs: [], inputStatuses: [], blockedBy: [] };
}

function statusIcon(status: StepStatus) {
  if (status === 'complete') return <Check size={14} />;
  if (status === 'skipped') return <SkipForward size={14} />;
  if (status === 'needs_link') return <Link2 size={14} />;
  if (status === 'blocked') return <Forward size={14} />;
  if (status === 'missing') return <AlertCircle size={14} />;
  return <Circle size={14} />;
}

function orderExplanation(step: FlowChecklistStep, checklist: FlowChecklist) {
  const dependencyLabels = step.depends_on
    .map((slotId) => checklist.steps.find((candidate) => candidate.slot_id === slotId)?.label || slotId);
  const parts: string[] = [];
  if (dependencyLabels.length > 0) parts.push(`After ${dependencyLabels.join(', ')}`);
  if (step.input_requirements.length > 0) parts.push(`Needs ${step.input_requirements.join(', ')}`);
  return parts.join(' · ');
}

function connectionMessage(connected: number, skipped: Array<{ schema: string; target_input: string; reason: string }>) {
  const missing = skipped.filter((item) => !['already_connected'].includes(item.reason));
  if (connected === 0 && missing.length === 0) return 'No new links were needed.';
  if (missing.length === 0) return `Connected ${connected} link${connected === 1 ? '' : 's'}.`;
  const missingText = missing.map((item) => `${item.target_input}: ${connectSkipReasonText(item.reason)}`).join(', ');
  return `Connected ${connected} link${connected === 1 ? '' : 's'}; still missing ${missingText}.`;
}

function progressSummary(stepStates: Map<string, StepState>, checklist: FlowChecklist) {
  const states = checklist.steps.map((step) => stepStates.get(step.slot_id)?.status || (step.required ? 'missing' : 'optional'));
  const done = states.filter((status) => status === 'complete').length;
  const skipped = states.filter((status) => status === 'skipped').length;
  const needsLink = states.filter((status) => status === 'needs_link').length;
  const missing = states.filter((status) => status === 'missing' || status === 'blocked').length;
  const percent = checklist.steps.length > 0 ? Math.round(((done + skipped) / checklist.steps.length) * 100) : 0;
  return { done, skipped, needsLink, missing, percent };
}

function nextActionStep(checklist: FlowChecklist, stepStates: Map<string, StepState>) {
  const needsLink = checklist.steps.find((step) => stepStates.get(step.slot_id)?.status === 'needs_link');
  if (needsLink) return { step: needsLink, action: 'link' as const, text: `Next: Link ${needsLink.label}` };
  const missing = checklist.steps.find((step) => {
    const status = stepStates.get(step.slot_id)?.status;
    return status === 'missing' || status === 'optional';
  });
  if (missing) return { step: missing, action: 'add' as const, text: `Next: Add ${missing.label}` };
  const blocked = checklist.steps.find((step) => stepStates.get(step.slot_id)?.status === 'blocked');
  if (blocked) return { step: blocked, action: 'blocked' as const, text: `Next: Complete prerequisites for ${blocked.label}` };
  const skipped = checklist.steps.find((step) => stepStates.get(step.slot_id)?.status === 'skipped');
  if (skipped) return { step: skipped, action: 'review' as const, text: `Next: Review skipped ${skipped.label}` };
  return null;
}

export function FlowChecklistPanel({
  flow,
  onChange,
  onFocusAtom,
  onActiveStepChange,
  focusedSlotId,
  readOnly = false,
}: FlowChecklistPanelProps) {
  const [checklist, setChecklist] = useState<FlowChecklist | null>(null);
  const [summaries, setSummaries] = useState<FlowChecklistSummary[]>([]);
  const [scenarioId, setScenarioId] = useState('task_glm');
  const [templates, setTemplates] = useState<AtomTemplate[]>([]);
  const [emptySpecs, setEmptySpecs] = useState<EmptyMarkerSpec[]>([]);
  const [skipReasons, setSkipReasons] = useState<Record<string, string>>({});
  const [customSkipReasons, setCustomSkipReasons] = useState<Record<string, string>>({});
  const [connectMessageText, setConnectMessageText] = useState('');
  const [buildPreview, setBuildPreview] = useState<ReturnType<typeof buildChecklistMissingSequence> | null>(null);
  const stepRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    listFlowChecklists()
      .then((items) => setSummaries(Array.isArray(items) ? items : []))
      .catch(() => setSummaries([]));
    listAtomTemplates()
      .then((items) => setTemplates(Array.isArray(items) ? items : []))
      .catch(() => setTemplates([]));
    listEmptyMarkerSpecs()
      .then((items) => setEmptySpecs(Array.isArray(items) ? items : []))
      .catch(() => setEmptySpecs([]));
  }, []);

  const atoms = useMemo(() => flowAtoms(flow), [flow]);
  const checklistMetadata = useMemo(() => getChecklistMetadata(flow), [flow]);

  useEffect(() => {
    if (summaries.length === 0) return;
    const availableIds = new Set(summaries.map((item) => item.scenario_id));
    const storedScenarioId = String(checklistMetadata.scenario_id || '');
    const nextScenarioId = availableIds.has(storedScenarioId)
      ? storedScenarioId
      : inferChecklistScenario(flow);
    if (!availableIds.has(nextScenarioId)) return;
    if (scenarioId !== nextScenarioId) setScenarioId(nextScenarioId);
    if (!storedScenarioId && !readOnly && (Object.keys(flow).length > 0 || atoms.length > 0)) {
      onChange(withChecklistMetadata(flow, nextScenarioId, { recommendation_source: 'flow_atoms' }));
    }
  }, [atoms.length, checklistMetadata.scenario_id, flow, onChange, readOnly, scenarioId, summaries]);

  useEffect(() => {
    getFlowChecklist(scenarioId)
      .then((item) => setChecklist(Array.isArray(item.steps) ? item : null))
      .catch(() => setChecklist(null));
  }, [scenarioId]);

  const choices = useMemo(() => getChecklistChoices(flow), [flow]);
  const stepStates = useMemo(() => {
    const states = new Map<string, StepState>();
    const completed = new Set<string>();
    if (!checklist) return states;

    checklist.steps.forEach((step) => {
      const state = statusForStep(flow, step, atoms, completed);
      states.set(step.slot_id, state);
      if (state.status === 'complete' || state.status === 'skipped') {
        completed.add(step.slot_id);
      }
    });
    return states;
  }, [atoms, checklist, flow]);
  const summary = useMemo(
    () => (checklist ? progressSummary(stepStates, checklist) : { done: 0, skipped: 0, needsLink: 0, missing: 0, percent: 0 }),
    [checklist, stepStates]
  );
  const nextAction = useMemo(() => (checklist ? nextActionStep(checklist, stepStates) : null), [checklist, stepStates]);

  useEffect(() => {
    if (!focusedSlotId) return;
    const node = stepRefs.current[focusedSlotId];
    if (!node) return;
    node.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [focusedSlotId, stepStates]);

  if (!checklist) {
    return (
      <section className="checklist-panel">
        <div className="checklist-heading">
          <ListChecks size={16} />
          <h3>Flow Checklist</h3>
        </div>
        <p className="muted">Checklist guidance is unavailable.</p>
      </section>
    );
  }

  const selectedTemplateId = (step: FlowChecklistStep) =>
    choices[step.slot_id]?.template_id || step.default_template_id || step.recommended_template_ids[0] || '';

  const rememberChoice = (step: FlowChecklistStep, templateId: string) => {
    if (readOnly) return;
    onChange(withChecklistChoice(flow, checklist.scenario_id, step.slot_id, { template_id: templateId }));
  };

  const activateStep = (step: FlowChecklistStep) => {
    onActiveStepChange?.({
      scenarioId: checklist.scenario_id,
      slotId: step.slot_id,
      label: step.label,
      templateIds: checklistStepTemplateIds(step),
      recommendations: checklistTemplateRecommendations(step),
    });
  };

  const skipReasonForStep = (step: FlowChecklistStep) => {
    const choiceReason = choices[step.slot_id]?.skip_reason;
    const selected = skipReasons[step.slot_id] || choiceReason || 'reviewed_empty_processing';
    if (selected === 'custom') {
      return customSkipReasons[step.slot_id] || choiceReason || 'custom_empty_processing';
    }
    return selected;
  };

  const skipReasonSelectValue = (step: FlowChecklistStep) => {
    const reason = skipReasons[step.slot_id] || choices[step.slot_id]?.skip_reason || 'reviewed_empty_processing';
    return SKIP_REASON_OPTIONS.some((option) => option.value === reason) ? reason : 'custom';
  };

  const annotateSkippedEmptyAtom = (nextFlow: Record<string, unknown>, step: FlowChecklistStep, skipReason: string) => {
    const atomKey = atomCollectionKey(nextFlow);
    const nextAtoms = (Array.isArray(nextFlow[atomKey]) ? nextFlow[atomKey] : []).map((atom) => {
      const record = atom as Record<string, unknown>;
      const metadata = (record.metadata as Record<string, unknown>) || {};
      if (
        (record.operation === 'empty_marker' || record.atom_type === 'empty_marker' || metadata.empty_atom === true) &&
        metadata.skipped_processing_category === step.category
      ) {
        return { ...record, metadata: { ...metadata, checklist_slot_id: step.slot_id, skip_reason: skipReason } };
      }
      return record;
    });
    return {
      ...nextFlow,
      [atomKey]: nextAtoms,
      ...(atomKey === 'flow_atoms' && Array.isArray(nextFlow.nodes) ? { nodes: nextAtoms } : {}),
    };
  };

  const addStep = (step: FlowChecklistStep, index: number) => {
    if (readOnly) return;
    const template = findChecklistStepTemplate(step, templates, selectedTemplateId(step));
    if (!template) return;

    const baseFlow = withChecklistChoice(
      withChecklistMetadata(flow, checklist.scenario_id, { version: checklist.version }),
      checklist.scenario_id,
      step.slot_id,
      { template_id: template.id, skipped: false }
    );
    const added = addTemplateAtomToFlow(baseFlow, template, {
      x: 120 + (index % 3) * 250,
      y: 90 + Math.floor(index / 3) * 150,
    });
    const report = connectAtomRequiredInputsWithReport(added.flow, added.atom);
    setConnectMessageText(connectionMessage(report.connected_edges.length, report.skipped_inputs));
    onChange(withChecklistChoice(report.flow, checklist.scenario_id, step.slot_id, { atom_id: String(added.atom.id) }));
  };

  const skipStep = (step: FlowChecklistStep) => {
    if (readOnly || !step.allow_empty_marker) return;
    const skipReason = skipReasonForStep(step);
    const baseFlow = withChecklistChoice(
      withChecklistMetadata(withOrderPolicy(flow, { allow_empty_edges: true }), checklist.scenario_id, {
        version: checklist.version,
      }),
      checklist.scenario_id,
      step.slot_id,
      { skipped: true, skip_reason: skipReason }
    );
    onChange(annotateSkippedEmptyAtom(addEmptyMarkerForCategory(baseFlow, emptySpecs, step.category), step, skipReason));
  };

  const addMissingSequence = () => {
    if (readOnly) return;
    const preview = buildChecklistMissingSequence(
      withChecklistMetadata(flow, checklist.scenario_id, { version: checklist.version }),
      checklist,
      templates,
      choices
    );
    setBuildPreview(preview);
  };

  const applyBuildPreview = () => {
    if (!buildPreview) return;
    setConnectMessageText(connectionMessage(buildPreview.connected_edges.length, buildPreview.skipped_inputs));
    onChange(buildPreview.flow);
    setBuildPreview(null);
  };

  const connectSuggested = () => {
    if (readOnly) return;
    const report = connectChecklistAtomsWithReport(
      withChecklistMetadata(flow, checklist.scenario_id, { version: checklist.version }),
      checklist
    );
    setConnectMessageText(connectionMessage(report.connected_edges.length, report.skipped_inputs));
    onChange(report.flow);
  };

  const changeScenario = (nextScenarioId: string) => {
    setScenarioId(nextScenarioId);
    if (!readOnly) onChange(withChecklistMetadata(flow, nextScenarioId, { recommendation_source: 'user' }));
  };

  const exportChecklistReport = () => {
    const report = generateChecklistReport(flow, checklist);
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${checklist.scenario_id}_checklist_report.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="checklist-panel">
      <div className="checklist-heading">
        <ListChecks size={16} />
        <div>
          <h3>{checklist.label}</h3>
          <p>{checklist.description}</p>
        </div>
      </div>
      {summaries.length > 1 && (
        <label className="checklist-scenario-select">
          <span>Scenario</span>
          <select value={scenarioId} onChange={(event) => changeScenario(event.target.value)}>
            {summaries.map((item) => (
              <option key={item.scenario_id} value={item.scenario_id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="checklist-progress" aria-label="Checklist progress">
        <div>
          <strong>{summary.percent}%</strong>
          <span>complete</span>
        </div>
        <div className="checklist-progress-track">
          <span style={{ width: `${summary.percent}%` }} />
        </div>
        <div className="checklist-progress-counts">
          <span>{summary.done} done</span>
          <span>{summary.needsLink} need links</span>
          <span>{summary.missing} missing</span>
          <span>{summary.skipped} skipped</span>
        </div>
      </div>
      {nextAction && (
        <div className="checklist-next-action">
          <span>{nextAction.text}</span>
          <button
            className="icon-text-button subtle"
            disabled={readOnly || nextAction.action === 'blocked'}
            onClick={() => {
              activateStep(nextAction.step);
              const state = stepStates.get(nextAction.step.slot_id);
              if (nextAction.action === 'link' && state?.atom) {
                const report = connectAtomRequiredInputsWithReport(flow, state.atom as Record<string, unknown>);
                setConnectMessageText(connectionMessage(report.connected_edges.length, report.skipped_inputs));
                onChange(report.flow);
              } else if (nextAction.action === 'add') {
                addStep(nextAction.step, checklist.steps.indexOf(nextAction.step));
              }
            }}
            type="button"
          >
            <Forward size={14} />
            Go
          </button>
        </div>
      )}
      <div className="checklist-toolbar">
        <button className="icon-text-button" disabled={readOnly} onClick={addMissingSequence} type="button">
          <Plus size={14} />
          Add missing
        </button>
        <button className="icon-text-button subtle" disabled={readOnly} onClick={connectSuggested} type="button">
          <Forward size={14} />
          Connect
        </button>
        <button className="icon-text-button subtle" onClick={exportChecklistReport} type="button">
          <ListChecks size={14} />
          Report
        </button>
      </div>
      {buildPreview && (
        <div className="checklist-preview">
          <strong>Add missing preview</strong>
          {buildPreview.added_atoms.length === 0 ? (
            <p>No new atoms are needed for currently available steps.</p>
          ) : (
            <p>
              Add {buildPreview.added_atoms.length} atom{buildPreview.added_atoms.length === 1 ? '' : 's'} and connect {buildPreview.connected_edges.length} link{buildPreview.connected_edges.length === 1 ? '' : 's'}.
            </p>
          )}
          {buildPreview.added_atoms.length > 0 && (
            <ul>
              {buildPreview.added_atoms.map((atom) => (
                <li key={atom.atom_id}>{atom.label}: <code>{atom.template_id}</code></li>
              ))}
            </ul>
          )}
          {buildPreview.skipped_inputs.filter((input) => input.reason !== 'already_connected').length > 0 && (
            <p>Still missing: {buildPreview.skipped_inputs.filter((input) => input.reason !== 'already_connected').map((input) => `${input.target_input}: ${connectSkipReasonText(input.reason)}`).join(', ')}</p>
          )}
          <div className="checklist-preview-actions">
            <button className="icon-text-button" disabled={readOnly} onClick={applyBuildPreview} type="button">
              Apply
            </button>
            <button className="icon-text-button subtle" onClick={() => setBuildPreview(null)} type="button">
              Cancel
            </button>
          </div>
        </div>
      )}
      {connectMessageText && (
        <div className="checklist-feedback" role="status">
          {connectMessageText}
        </div>
      )}

      <div className="checklist-steps">
        {checklist.steps.map((step, index) => {
          const state = stepStates.get(step.slot_id) || {
            status: 'missing' as StepStatus,
            missingInputs: [],
            inputStatuses: [],
            blockedBy: [],
          };
          const status = state.status;
          const blocked = status === 'blocked';
          const templateIds = checklistStepTemplateIds(step).filter((id) =>
            templates.some((template) => template.id === id || template.operation === id)
          );
          const templateAvailable = templateIds.length > 0;
          const selectedId = selectedTemplateId(step);
          const focusAtom = state.atom;
          const requiredInputs = state.inputStatuses.filter((input) => input.required);
          const connectedInputs = requiredInputs.filter((input) => input.connected);
          const blockedLabels = state.blockedBy.map(
            (slotId) => checklist.steps.find((candidate) => candidate.slot_id === slotId)?.label || slotId
          );
          return (
            <div
              key={step.slot_id}
              ref={(node) => { stepRefs.current[step.slot_id] = node; }}
              className={`checklist-step ${status} ${focusAtom ? 'focusable' : ''} ${focusedSlotId === step.slot_id ? 'selected' : ''} ${nextAction?.step.slot_id === step.slot_id ? 'priority' : ''}`}
              onClick={() => activateStep(step)}
            >
              <div className="checklist-step-main">
                <span className="checklist-step-status">{statusIcon(status)}</span>
                <div>
                  <div className="checklist-step-title">
                    <span>{index + 1}. {step.label}</span>
                    <span className={step.required ? 'required' : 'recommended'}>
                      {step.required ? 'Required' : 'Recommended'}
                    </span>
                  </div>
                  <p>{step.guidance}</p>
                  {orderExplanation(step, checklist) && (
                    <p className="checklist-step-order">{orderExplanation(step, checklist)}</p>
                  )}
                  <div className="checklist-step-meta">
                    <code>{selectedId || step.recommended_template_ids.join(' / ')}</code>
                    {requiredInputs.length > 0 && (
                      <span>{connectedInputs.length}/{requiredInputs.length} inputs connected</span>
                    )}
                    {state.missingInputs.length > 0 && <span>Needs input: {state.missingInputs.join(', ')}</span>}
                    {blockedLabels.length > 0 && <span>Blocked by {blockedLabels.join(', ')}</span>}
                  </div>
                  {templateIds.length > 1 && (
                    <select
                      className="checklist-template-select"
                      disabled={readOnly || status === 'complete'}
                      value={templateIds.includes(selectedId) ? selectedId : templateIds[0]}
                      onChange={(event) => rememberChoice(step, event.target.value)}
                      onClick={(event) => event.stopPropagation()}
                    >
                      {templateIds.map((id) => (
                        <option key={id} value={id}>
                          {id}
                        </option>
                      ))}
                    </select>
                  )}
                  {step.allow_empty_marker && (
                    <div className="checklist-skip-reason" onClick={(event) => event.stopPropagation()}>
                      <select
                        disabled={readOnly || blocked || status === 'skipped'}
                        value={skipReasonSelectValue(step)}
                        onChange={(event) => {
                          const value = event.target.value;
                          setSkipReasons((current) => ({ ...current, [step.slot_id]: value }));
                          if (value !== 'custom') {
                            onChange(withChecklistChoice(flow, checklist.scenario_id, step.slot_id, { skip_reason: value }));
                          }
                        }}
                      >
                        {SKIP_REASON_OPTIONS.map((reason) => (
                          <option key={reason.value} value={reason.value}>
                            {reason.label}
                          </option>
                        ))}
                      </select>
                      {skipReasonSelectValue(step) === 'custom' && (
                        <input
                          disabled={readOnly || blocked || status === 'skipped'}
                          placeholder="Skip reason"
                          value={customSkipReasons[step.slot_id] || choices[step.slot_id]?.skip_reason || ''}
                          onChange={(event) => {
                            const value = event.target.value;
                            setCustomSkipReasons((current) => ({ ...current, [step.slot_id]: value }));
                            onChange(withChecklistChoice(flow, checklist.scenario_id, step.slot_id, {
                              skip_reason: value || 'custom_empty_processing',
                            }));
                          }}
                        />
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div className="checklist-step-actions" onClick={(event) => event.stopPropagation()}>
                <button
                  className="icon-text-button"
                  disabled={readOnly || blocked || !templateAvailable || status === 'complete'}
                  onClick={() => addStep(step, index)}
                  type="button"
                >
                  <Plus size={14} />
                  Add
                </button>
                {status === 'needs_link' && state.atom && (
                  <button
                    className="icon-text-button subtle"
                    disabled={readOnly}
                    onClick={() => {
                      const report = connectAtomRequiredInputsWithReport(flow, state.atom as Record<string, unknown>);
                      setConnectMessageText(connectionMessage(report.connected_edges.length, report.skipped_inputs));
                      onChange(report.flow);
                    }}
                    type="button"
                  >
                    <Link2 size={14} />
                    Link
                  </button>
                )}
                {focusAtom && (
                  <button
                    className="icon-text-button subtle"
                    disabled={readOnly}
                    onClick={() => onFocusAtom?.(String(focusAtom.id))}
                    type="button"
                  >
                    <Forward size={14} />
                    Focus
                  </button>
                )}
                {step.allow_empty_marker && (
                  <button
                    className="icon-text-button subtle"
                    disabled={readOnly || blocked || status === 'skipped' || emptySpecs.length === 0}
                    onClick={() => skipStep(step)}
                    type="button"
                  >
                    <SkipForward size={14} />
                    Skip
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
