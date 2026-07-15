import { useState } from 'react';
import { useStore } from '../store';
import { AIDraftReviewPanel } from '../components/AIDraftReviewPanel';
import { FlowCanvas } from '../components/FlowCanvas';
import { Sidebar } from '../components/Sidebar';
import { ValidationPanel } from '../components/ValidationPanel';

export function FlowBuilder() {
  const [showAIDraft, setShowAIDraft] = useState(false);
  const [configuringNode, setConfiguringNode] = useState(false);
  const project = useStore((s) => s.project);
  const flow = useStore((s) => s.flow);
  const setFlow = useStore((s) => s.setFlow);
  const validation = useStore((s) => s.validation);
  const readOnly = useStore((s) => s.importStatus?.read_only ?? false);

  return (
    <div className={`canvas-layout ${configuringNode && !showAIDraft ? 'configuring-node' : ''}`}>
      <Sidebar />
      <div className="canvas-container">
        <FlowCanvas
          flow={flow}
          onChange={setFlow}
          readOnly={readOnly}
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
        !configuringNode && <ValidationPanel result={validation} onOpenAIDraft={() => setShowAIDraft(true)} />
      )}
    </div>
  );
}
