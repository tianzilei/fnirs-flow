import { useEffect, useState } from 'react';
import { formatApiError, getExampleFlow, listExampleFlows, type ExampleFlowSummary } from '../api/client';
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
  const [examples, setExamples] = useState<ExampleFlowSummary[]>([]);
  const [loadingExample, setLoadingExample] = useState('');
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

  useEffect(() => {
    let active = true;
    listExampleFlows()
      .then((items) => {
        if (active) setExamples(items);
      })
      .catch(() => {
        if (active) setExamples([]);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleLoadExample = async (exampleId: string) => {
    if (readOnly) return;
    setLoadingExample(exampleId);
    try {
      const nextFlow = await getExampleFlow(exampleId);
      setFlow(nextFlow);
      useStore.setState({
        error: {
          message: 'Example flow loaded',
          detail: `${String(nextFlow.flow_id || exampleId)} is ready to review and save.`,
        },
      });
    } catch (error) {
      useStore.setState({ error: { message: 'Example flow failed', detail: formatApiError(error) } });
    } finally {
      setLoadingExample('');
    }
  };

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
            {examples.length > 0 && !readOnly && (
              <section className="workflow-panel example-flow-panel">
                <div className="section-heading compact">
                  <div>
                    <h3>Example Flow</h3>
                  </div>
                </div>
                <div className="example-flow-actions">
                  {examples.map((example) => (
                    <button
                      key={example.id}
                      className="ghost-button compact"
                      onClick={() => handleLoadExample(example.id)}
                      disabled={!!loadingExample}
                    >
                      {loadingExample === example.id ? 'Loading...' : example.label}
                    </button>
                  ))}
                </div>
              </section>
            )}
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
