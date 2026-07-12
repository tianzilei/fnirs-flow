import { useStore } from '../store';
import { FlowCanvas } from '../components/FlowCanvas';
import { Sidebar } from '../components/Sidebar';
import { ValidationPanel } from '../components/ValidationPanel';

export function FlowBuilder() {
  const flow = useStore((s) => s.flow);
  const setFlow = useStore((s) => s.setFlow);
  const validation = useStore((s) => s.validation);

  return (
    <div className="canvas-layout">
      <Sidebar />
      <div className="canvas-container">
        <FlowCanvas flow={flow} onChange={setFlow} />
      </div>
      <ValidationPanel result={validation} />
    </div>
  );
}
