import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  ReactFlowInstance,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  useNodesState,
  useEdgesState,
  Connection,
  NodeChange,
  EdgeChange,
  NodeMouseHandler,
} from 'reactflow';
import {
  Activity,
  AlertTriangle,
  Braces,
  Cable,
  CircleDot,
  Database,
  FileOutput,
  FlaskConical,
  Gauge,
  Play,
  ShieldCheck,
} from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import 'reactflow/dist/style.css';
import { listEmptyMarkerSpecs, type AtomTemplate, type EmptyMarkerSpec } from '../api/client';
import {
  addMissingEmptyMarkerAtoms,
  addTemplateAtomToFlow,
  atomCollectionKey,
  asRecords,
  clearChecklistChoiceForAtom,
  connectionProblem,
  findPort,
  flowAtoms as getFlowAtoms,
  getAtomInputStatuses,
  getAtomPorts,
  getOrderPolicy,
  previewEmptyRiskRemoval,
  removeUnconnectedAutoEmptyMarkerAtoms,
  withChecklistChoice,
  withOrderPolicy,
} from '../flow/atomFactory';
import { ParameterPanel } from './ParameterPanel';

interface FlowCanvasProps {
  flow: Record<string, unknown>;
  onChange: (flow: Record<string, unknown>) => void;
  readOnly?: boolean;
  focusedAtomId?: string | null;
  activeChecklistStep?: { scenarioId: string; slotId: string; label?: string; templateIds: string[] } | null;
  onInspectingChange?: (inspecting: boolean) => void;
}

const nodeColors: Record<string, string> = {
  data: '#0f766e',
  design: '#2563eb',
  preprocessing: '#b45309',
  analysis: '#7c3aed',
  output: '#0284c7',
  validation: '#dc2626',
  export: '#57534e',
};

const categoryIcons: Record<string, typeof Database> = {
  data: Database,
  design: FlaskConical,
  preprocessing: Gauge,
  analysis: Activity,
  output: FileOutput,
  validation: ShieldCheck,
  export: Braces,
};

interface NodeDetail {
  id: string;
  atom_type: string;
  operation: string;
  category: string;
  readiness_status: string;
  config: Record<string, unknown>;
  parameters: Record<string, unknown>;
  ports: Array<{ name: string; direction: string; schema: string }>;
}

function portCount(atom: Record<string, unknown>, key: string, fallback: string) {
  return asRecords(atom[key]).length || asRecords(atom[fallback]).length || getAtomPorts(atom).filter((port) =>
    key === 'input_ports' ? port.direction === 'in' : port.direction === 'out'
  ).length;
}

function NodeLabel({
  atom,
  missingInputs,
  emptyAtom,
  focused,
}: {
  atom: Record<string, unknown>;
  missingInputs: boolean;
  emptyAtom: boolean;
  focused: boolean;
}) {
  const category = String(atom.category || 'node');
  const atomType = String(atom.atom_type || atom.type || atom.id || 'Atom');
  const operation = String(atom.operation || atomType);
  const Icon = categoryIcons[category] || CircleDot;

  return (
    <div className="flow-node-card">
      <div className="flow-node-topline">
        <span className="flow-node-icon" style={{ color: nodeColors[category] || '#525252' }}>
          <Icon size={15} strokeWidth={2.2} />
        </span>
        <span className="flow-node-category">{category}</span>
      </div>
      <div className="flow-node-title">{atomType}</div>
      {operation && operation !== atomType && <div className="flow-node-operation">{operation}</div>}
      <div className="flow-node-meta">
        <span>{portCount(atom, 'input_ports', 'inputs')} in</span>
        <span>{portCount(atom, 'output_ports', 'outputs')} out</span>
      </div>
      {(missingInputs || emptyAtom || focused) && (
        <div className="flow-node-badges">
          {focused && <span>Checklist</span>}
          {missingInputs && <span>Missing input</span>}
          {emptyAtom && <span>Empty</span>}
        </div>
      )}
    </div>
  );
}

function toNodes(flow: Record<string, unknown>, focusedAtomId?: string | null): Node[] {
  const flowAtoms = asRecords(flow.flow_atoms).length > 0 ? asRecords(flow.flow_atoms) : asRecords(flow.nodes);
  return flowAtoms.map((atom) => ({
    ...(() => {
      const metadata = (atom.metadata as Record<string, unknown>) || {};
      const emptyAtom = atom.operation === 'empty_marker' || atom.atom_type === 'empty_marker' || metadata.empty_atom === true;
      const missingInputs = getAtomInputStatuses(flow, atom).some((input) => input.required && !input.connected);
      const focused = String(atom.id) === String(focusedAtomId || '');
      return {
        id: String(atom.id),
        position: (atom.position as { x: number; y: number }) ?? { x: 0, y: 0 },
        data: { label: <NodeLabel atom={atom} missingInputs={missingInputs} emptyAtom={emptyAtom} focused={focused} /> },
        style: {
          background: 'transparent',
          border: 'none',
          boxShadow: 'none',
          padding: 0,
          cursor: 'pointer',
        },
        className: `flow-node flow-node-${String(atom.category || 'default')} ${missingInputs ? 'flow-node-missing-inputs' : ''} ${emptyAtom ? 'flow-node-empty' : ''} ${focused ? 'flow-node-focused' : ''}`,
      };
    })(),
  }));
}

function toEdges(flow: Record<string, unknown>): Edge[] {
  return asRecords(flow.edges).map((edge) => ({
    id: String(edge.id),
    source: String(edge.source),
    target: String(edge.target),
    sourceHandle: edge.source_handle ? String(edge.source_handle) : undefined,
    targetHandle: edge.target_handle ? String(edge.target_handle) : undefined,
    animated: true,
    className: 'flow-edge',
  }));
}

function syncFlow(flow: Record<string, unknown>, nodes: Node[], edges: Edge[]): Record<string, unknown> {
  const atomKey = Array.isArray(flow.flow_atoms) ? 'flow_atoms' : 'nodes';
  const existingAtoms = asRecords(flow[atomKey]);
  const atomById = new Map(existingAtoms.map((atom) => [String(atom.id), atom]));
  const nextAtoms = nodes.map((node) => ({
    ...(atomById.get(String(node.id)) || { id: String(node.id), type: String(node.id) }),
    id: String(node.id),
    position: node.position,
  }));
  const nextEdges = edges.map((edge, index) => {
    const source = String(edge.source);
    const target = String(edge.target);
    const sourcePort = findPort(atomById.get(source), edge.sourceHandle, 'out');
    const targetPort = findPort(atomById.get(target), edge.targetHandle, 'in');
    return {
      id: String(edge.id || `edge-${index + 1}`),
      source,
      target,
      source_handle: String(edge.sourceHandle || sourcePort?.name || 'output'),
      target_handle: String(edge.targetHandle || targetPort?.name || 'input'),
    };
  });
  const nextFlow = {
    ...flow,
    [atomKey]: nextAtoms,
    edges: nextEdges,
  };
  if (atomKey === 'flow_atoms' && Array.isArray(flow.nodes)) {
    nextFlow.nodes = nextAtoms;
  }
  return nextFlow;
}

function shouldSyncNodeChanges(changes: NodeChange[]): boolean {
  return changes.some((change) => ['position', 'remove'].includes(change.type));
}

function shouldSyncEdgeChanges(changes: EdgeChange[]): boolean {
  return changes.some((change) => change.type === 'remove');
}

function normalizePorts(atom: Record<string, unknown>): NodeDetail['ports'] {
  return getAtomPorts(atom).map((port) => ({
    name: port.name,
    direction: port.direction,
    schema: port.schema,
  }));
}

function atomToDetail(atom: Record<string, unknown>): NodeDetail {
  return {
    id: String(atom.id),
    atom_type: String(atom.atom_type || atom.type || ''),
    operation: String(atom.operation || ''),
    category: String(atom.category || ''),
    readiness_status: String(atom.readiness_status || atom.status || ''),
    config: (atom.config as Record<string, unknown>) || {},
    parameters: (atom.parameters as Record<string, unknown>) || {},
    ports: normalizePorts(atom),
  };
}

export function FlowCanvas({
  flow,
  onChange,
  readOnly = false,
  focusedAtomId,
  activeChecklistStep,
  onInspectingChange,
}: FlowCanvasProps) {
  const [nodes, setNodes] = useNodesState([]);
  const [edges, setEdges] = useEdgesState([]);
  const [selectedNode, setSelectedNode] = useState<NodeDetail | null>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);
  const [connectionError, setConnectionError] = useState('');
  const [canvasNotice, setCanvasNotice] = useState('');
  const [emptyMarkerSpecs, setEmptyMarkerSpecs] = useState<EmptyMarkerSpec[]>([]);
  const [emptyRemovalPreview, setEmptyRemovalPreview] = useState<ReturnType<typeof previewEmptyRiskRemoval> | null>(null);
  const [searchParams] = useSearchParams();
  const nodesRef = useRef<Node[]>([]);
  const edgesRef = useRef<Edge[]>([]);
  const nodeCount = nodes.length;
  const edgeCount = edges.length;

  useEffect(() => {
    const nextNodes = toNodes(flow, focusedAtomId);
    const nextEdges = toEdges(flow);
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setNodes(nextNodes);
    setEdges(nextEdges);
  }, [flow, focusedAtomId, setNodes, setEdges]);

  useEffect(() => {
    listEmptyMarkerSpecs()
      .then(setEmptyMarkerSpecs)
      .catch(() => setEmptyMarkerSpecs([]));
  }, []);

  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

  const flowAtoms = useMemo(
    () => getFlowAtoms(flow),
    [flow]
  );
  const orderPolicy = useMemo(() => getOrderPolicy(flow), [flow]);

  useEffect(() => {
    const nodeId = searchParams.get('node');
    if (!nodeId) return;
    const atom = flowAtoms.find((item) => String(item.id) === nodeId);
    if (atom) {
      setSelectedNode(atomToDetail(atom));
      onInspectingChange?.(true);
    }
  }, [flowAtoms, onInspectingChange, searchParams]);

  useEffect(() => {
    if (!focusedAtomId) return;
    const atom = flowAtoms.find((item) => String(item.id) === focusedAtomId);
    if (!atom) return;
    setSelectedNode(atomToDetail(atom));
    onInspectingChange?.(true);
    const position = (atom.position as { x: number; y: number }) || undefined;
    if (position && reactFlowInstance) {
      reactFlowInstance.setCenter(position.x + 90, position.y + 40, { zoom: 1, duration: 300 });
    }
  }, [flowAtoms, focusedAtomId, onInspectingChange, reactFlowInstance]);

  const onConnect = useCallback(
    (params: Connection) => {
      if (readOnly) return;
      const problem = connectionProblem(params, flowAtoms, edgesRef.current, orderPolicy);
      if (problem) {
        setConnectionError(problem);
        return;
      }
      const source = params.source;
      const target = params.target;
      if (!source || !target) return;
      const sourceAtom = flowAtoms.find((atom) => String(atom.id) === source);
      const targetAtom = flowAtoms.find((atom) => String(atom.id) === target);
      const sourcePort = findPort(sourceAtom, params.sourceHandle, 'out');
      const targetPort = findPort(targetAtom, params.targetHandle, 'in');
      const edgeId = `edge-${source}-${target}-${edgesRef.current.length + 1}`;
      const nextEdges = addEdge(
        {
          ...params,
          id: edgeId,
          source,
          target,
          sourceHandle: params.sourceHandle || sourcePort?.name,
          targetHandle: params.targetHandle || targetPort?.name,
          animated: true,
          className: 'flow-edge',
        },
        edgesRef.current
      );
      edgesRef.current = nextEdges;
      setEdges(nextEdges);
      setConnectionError('');
      onChange(syncFlow(flow, nodesRef.current, nextEdges));
    },
    [flow, flowAtoms, onChange, orderPolicy, readOnly, setEdges]
  );

  const isValidConnection = useCallback(
    (connection: Connection) =>
      readOnly ? false : connectionProblem(connection, flowAtoms, edgesRef.current, orderPolicy) === null,
    [flowAtoms, orderPolicy, readOnly]
  );

  const toggleOrderRisk = useCallback(() => {
    if (readOnly) return;
    onChange(withOrderPolicy(flow, { allow_order_violations: !orderPolicy.allow_order_violations }));
  }, [flow, onChange, orderPolicy.allow_order_violations, readOnly]);

  const toggleEmptyRisk = useCallback(() => {
    if (readOnly) return;
    if (orderPolicy.allow_empty_edges) {
      const preview = previewEmptyRiskRemoval(flow);
      setEmptyRemovalPreview(preview);
      return;
    }
    const nextFlow = withOrderPolicy(flow, { allow_empty_edges: !orderPolicy.allow_empty_edges });
    onChange(
      !orderPolicy.allow_empty_edges
        ? addMissingEmptyMarkerAtoms(nextFlow, emptyMarkerSpecs)
        : removeUnconnectedAutoEmptyMarkerAtoms(nextFlow)
    );
  }, [emptyMarkerSpecs, flow, onChange, orderPolicy.allow_empty_edges, readOnly]);

  const applyEmptyRemoval = useCallback(() => {
    if (!emptyRemovalPreview) return;
    onChange(emptyRemovalPreview.flow);
    setEmptyRemovalPreview(null);
  }, [emptyRemovalPreview, onChange]);

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      if (readOnly) return;
      const nextNodes = applyNodeChanges(changes, nodesRef.current);
      nodesRef.current = nextNodes;
      setNodes(nextNodes);
      if (shouldSyncNodeChanges(changes)) {
        onChange(syncFlow(flow, nextNodes, edgesRef.current));
      }
    },
    [flow, onChange, readOnly, setNodes]
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      if (readOnly) return;
      const nextEdges = applyEdgeChanges(changes, edgesRef.current);
      edgesRef.current = nextEdges;
      setEdges(nextEdges);
      if (shouldSyncEdgeChanges(changes)) {
        onChange(syncFlow(flow, nodesRef.current, nextEdges));
      }
    },
    [flow, onChange, readOnly, setEdges]
  );

  const onNodeClick: NodeMouseHandler = useCallback(
    (_, node) => {
      const atom = flowAtoms.find((item) => String(item.id) === node.id);
      if (atom) {
        setSelectedNode(atomToDetail(atom));
        onInspectingChange?.(true);
      }
    },
    [flowAtoms, onInspectingChange]
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
    onInspectingChange?.(false);
  }, [onInspectingChange]);

  const deleteSelectedNode = useCallback(() => {
    if (readOnly || !selectedNode) return;
    const removedAtom = flowAtoms.find((atom) => String(atom.id) === selectedNode.id);
    const nextNodes = nodesRef.current.filter((node) => node.id !== selectedNode.id);
    const nextEdges = edgesRef.current.filter(
      (edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id
    );
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setNodes(nextNodes);
    setEdges(nextEdges);
    setSelectedNode(null);
    onInspectingChange?.(false);
    const syncedFlow = syncFlow(flow, nextNodes, nextEdges);
    onChange(removedAtom ? clearChecklistChoiceForAtom(syncedFlow, removedAtom) : syncedFlow);
  }, [flow, flowAtoms, onChange, onInspectingChange, readOnly, selectedNode, setEdges, setNodes]);

  useEffect(() => {
    if (readOnly || !selectedNode) return undefined;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Delete' && event.key !== 'Backspace') return;
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName.toLowerCase();
      const editingText = target?.isContentEditable || ['input', 'textarea', 'select'].includes(tagName || '');
      if (editingText) return;

      event.preventDefault();
      deleteSelectedNode();
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [deleteSelectedNode, readOnly, selectedNode]);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      if (readOnly) return;
      if (!reactFlowInstance) return;

      const payload = event.dataTransfer.getData('application/atom-template');
      if (!payload) return;

      const template = JSON.parse(payload) as AtomTemplate;
      const position = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      const added = addTemplateAtomToFlow(flow, template, position);
      let nextFlow = added.flow;
      const matchesActiveStep = activeChecklistStep?.templateIds.includes(template.id) ||
        activeChecklistStep?.templateIds.includes(template.operation);
      if (activeChecklistStep && !matchesActiveStep) {
        setCanvasNotice(`This atom is outside the selected checklist step: ${activeChecklistStep.label || activeChecklistStep.slotId}.`);
      } else {
        setCanvasNotice('');
      }
      if (activeChecklistStep && matchesActiveStep) {
        const atomKey = atomCollectionKey(nextFlow);
        const nextAtoms = asRecords(nextFlow[atomKey]).map((atom) => {
          if (String(atom.id) !== String(added.atom.id)) return atom;
          const metadata = (atom.metadata as Record<string, unknown>) || {};
          return { ...atom, metadata: { ...metadata, checklist_slot_id: activeChecklistStep.slotId } };
        });
        nextFlow = {
          ...nextFlow,
          [atomKey]: nextAtoms,
          ...(atomKey === 'flow_atoms' && Array.isArray(nextFlow.nodes) ? { nodes: nextAtoms } : {}),
        };
        nextFlow = withChecklistChoice(nextFlow, activeChecklistStep.scenarioId, activeChecklistStep.slotId, {
          template_id: template.id,
          atom_id: String(added.atom.id),
          skipped: false,
        });
      }
      onChange(nextFlow);
    },
    [activeChecklistStep, flow, onChange, reactFlowInstance, readOnly]
  );

  return (
    <div className="flow-canvas-shell">
      <div className="flow-canvas-stage" onDragOver={onDragOver} onDrop={onDrop}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={handleNodesChange}
          onEdgesChange={handleEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onInit={setReactFlowInstance}
          nodesDraggable={!readOnly}
          nodesConnectable={!readOnly}
          edgesUpdatable={!readOnly}
          deleteKeyCode={readOnly ? null : ['Backspace', 'Delete']}
          fitView
        >
          <Background color="#d7dee8" gap={18} />
          <Controls className="canvas-controls" />
          <MiniMap className="canvas-minimap" pannable zoomable />
        </ReactFlow>
        <div className="canvas-status-pill">
          <Play size={14} />
          <span>{nodeCount} atoms</span>
          <Cable size={14} />
          <span>{edgeCount} links</span>
        </div>
        <div className="canvas-risk-controls">
          <button
            className={orderPolicy.allow_order_violations ? 'active' : ''}
            onClick={toggleOrderRisk}
            disabled={readOnly}
            title="Allow order violations as reviewed risks"
            type="button"
          >
            <AlertTriangle size={14} />
            <span>Order risk</span>
          </button>
          <button
            className={orderPolicy.allow_empty_edges ? 'active' : ''}
            onClick={toggleEmptyRisk}
            disabled={readOnly || (!orderPolicy.allow_empty_edges && emptyMarkerSpecs.length === 0)}
            title="Allow empty links as reviewed risks"
            type="button"
          >
            <CircleDot size={14} />
            <span>Empty risk</span>
          </button>
        </div>
        {connectionError && (
          <div className="canvas-connection-error">
            <AlertTriangle size={14} />
            <span>{connectionError}</span>
          </div>
        )}
        {canvasNotice && (
          <div className="canvas-checklist-notice">
            <AlertTriangle size={14} />
            <span>{canvasNotice}</span>
          </div>
        )}
        {emptyRemovalPreview && (
          <div className="canvas-empty-removal-preview" role="dialog" aria-label="Disable Empty risk">
            <strong>Disable Empty risk?</strong>
            <span>
              Remove {emptyRemovalPreview.removed_atoms.length} empty atom{emptyRemovalPreview.removed_atoms.length === 1 ? '' : 's'}
              {emptyRemovalPreview.cleared_slots.length > 0 ? ` and clear ${emptyRemovalPreview.cleared_slots.length} skip marker${emptyRemovalPreview.cleared_slots.length === 1 ? '' : 's'}` : ''}.
            </span>
            <div>
              <button className="icon-text-button" onClick={applyEmptyRemoval} type="button">Apply</button>
              <button className="icon-text-button subtle" onClick={() => setEmptyRemovalPreview(null)} type="button">Cancel</button>
            </div>
          </div>
        )}
        {nodeCount === 0 && (
          <div className="canvas-empty-hint">
            <CircleDot size={18} />
            <span>Drag Method Atoms from the library onto the canvas.</span>
          </div>
        )}
      </div>
      {selectedNode && (
        <aside className="inspection-panel">
          <div className="inspection-header">
            <span className="inspection-kicker">{selectedNode.category || 'atom'}</span>
            <h3>{selectedNode.atom_type}</h3>
            <p>{selectedNode.operation || 'No operation assigned'}</p>
          </div>
          <dl className="inspection-facts">
            <div>
              <dt>ID</dt>
              <dd>{selectedNode.id}</dd>
            </div>
            <div>
              <dt>Operation</dt>
              <dd>{selectedNode.operation || '-'}</dd>
            </div>
          </dl>
          {selectedNode.ports.length > 0 && (
            <section className="inspection-section">
              <h4>Ports</h4>
              {selectedNode.ports.map((port) => (
                <div key={`${port.direction}-${port.name}`} className="port-row">
                  <span className={`port-dot ${port.direction}`} />
                  <span>{port.name}</span>
                  <code>{port.schema}</code>
                </div>
              ))}
            </section>
          )}
          <ParameterPanel
            title="Parameters"
            parameters={Object.entries({ ...selectedNode.config, ...selectedNode.parameters }).map(([name, value]) => ({
              name,
              type: typeof value === 'boolean' ? 'boolean' : typeof value === 'number' ? 'number' : 'text',
              value,
            }))}
            onChange={(name, value) => {
              if (readOnly) return;
              const updatedConfig = { ...selectedNode.config, [name]: value };
              const nextReadiness = selectedNode.readiness_status === 'not_configured'
                ? 'configured'
                : selectedNode.readiness_status;
              setSelectedNode({ ...selectedNode, config: updatedConfig, readiness_status: nextReadiness });
              const atomKey = Array.isArray(flow.flow_atoms) ? 'flow_atoms' : 'nodes';
              const nextAtoms = asRecords(flow[atomKey]).map((atom) =>
                String(atom.id) === selectedNode.id
                  ? { ...atom, config: updatedConfig, readiness_status: nextReadiness }
                  : atom
              );
              onChange({
                ...flow,
                [atomKey]: nextAtoms,
                ...(atomKey === 'flow_atoms' && Array.isArray(flow.nodes) ? { nodes: nextAtoms } : {}),
              });
            }}
            atomInfo={{
              atom_id: selectedNode.id,
              atom_type: selectedNode.atom_type,
              operation: selectedNode.operation,
              readiness_status: selectedNode.readiness_status,
            }}
          />
        </aside>
      )}
    </div>
  );
}
