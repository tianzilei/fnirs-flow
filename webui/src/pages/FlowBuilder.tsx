import { useState } from 'react';
import { useStore } from '../store';
import { AIDraftReviewPanel } from '../components/AIDraftReviewPanel';
import { FlowCanvas } from '../components/FlowCanvas';
import { FlowChecklistPanel } from '../components/FlowChecklistPanel';
import { Sidebar } from '../components/Sidebar';
import { ValidationPanel } from '../components/ValidationPanel';

export function FlowBuilder() {
  const [showAIDraft, setShowAIDraft] = useState(false);
  const [configuringNode, setConfiguringNode] = useState(false);
  const [focusedAtomId, setFocusedAtomId] = useState<string | null>(null);
  const [focusedChecklistSlotId, setFocusedChecklistSlotId] = useState<string | null>(null);
  const [activeChecklistStep, setActiveChecklistStep] = useState<{
    scenarioId: string;
    slotId: string;
    label: string;
    templateIds: string[];
    recommendations: Array<{ template_id: string; tier: 'best' | 'recommended' | 'alternative' | 'off_path' }>;
  } | null>(null);
  const project = useStore((s) => s.project);
  const flow = useStore((s) => s.flow);
  const setFlow = useStore((s) => s.setFlow);
  const validation = useStore((s) => s.validation);
  const readOnly = useStore((s) => s.importStatus?.read_only ?? false);

  const handleRiskSelect = (risk: Record<string, unknown>) => {
    const affectedObject = String(risk.affected_object || '');
    if (affectedObject.startsWith('checklist:')) {
      setConfiguringNode(false);
      setFocusedChecklistSlotId(affectedObject.slice('checklist:'.length));
    }
  };

  return (
    <div className={`canvas-layout ${configuringNode && !showAIDraft ? 'configuring-node' : ''}`}>
      <Sidebar
        highlightedTemplateIds={activeChecklistStep?.templateIds || []}
        checklistRecommendations={activeChecklistStep?.recommendations || []}
        activeChecklistLabel={activeChecklistStep?.label || ''}
      />
      <div className="canvas-container">
        <FlowCanvas
          flow={flow}
          onChange={setFlow}
          readOnly={readOnly}
          focusedAtomId={focusedAtomId}
          activeChecklistStep={activeChecklistStep}
          onInspectingChange={setConfiguringNode}
        />
      </div>
      {showAIDraft && project ? (
        <AIDraftReviewPanel
          projectId={project.id}
          projectName={project.name}
          currentFlow={flow}
          onApplied={setFlow}
          onClose={() => setShowAIDraft(false)}
        />
      ) : (
        !configuringNode && (
          <div className="flow-side-stack">
            <FlowChecklistPanel
              flow={flow}
              onChange={setFlow}
              onFocusAtom={setFocusedAtomId}
              onActiveStepChange={setActiveChecklistStep}
              focusedSlotId={focusedChecklistSlotId}
              readOnly={readOnly}
            />
            <ValidationPanel
              result={validation}
              onOpenAIDraft={() => setShowAIDraft(true)}
              onRiskSelect={handleRiskSelect}
            />
          </div>
        )
      )}
    </div>
  );
}
