import { type CSSProperties, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MiniMap,
  Node,
  Edge,
  Position,
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
  NodeProps,
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
import { listAtomTemplates, listEmptyMarkerSpecs, listProjectDataFolders, type AtomTemplate, type EmptyMarkerSpec } from '../api/client';
import {
  addMissingEmptyMarkerAtoms,
  addTemplateAtomToFlow,
  atomCollectionKey,
  asRecords,
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
import { useModalDialog } from '../utils/useModalDialog';
import { ParameterPanel } from './ParameterPanel';
import { useStore } from '../store';
import {
  shouldSyncNodeChanges,
  syncCanvasFlow as syncFlow,
} from '../features/flow/canvasModel';
import { shouldSyncEdgeChanges, toCanvasEdges as toEdges } from '../features/flow/edgeModel';
import {
  atomToDetailWithDefaults,
  type NodeDetail,
  parameterOptionsForNode,
  parameterSpecForNode,
  parameterTypeForValue,
  visibleParameterEntries,
} from '../features/flow/nodeModel';
import { deleteAtomCommand } from '../features/flow/commands';
import { selectAtomDetail } from '../features/flow/selectionModel';

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

function FlowAtomNode({ data }: NodeProps<{ label: ReactNode }>) {
  return <>{data.label}</>;
}

const nodeTypes = {
  flowAtom: FlowAtomNode,
};

interface PortNeighbor {
  id: string;
  atomType: string;
  category: string;
  color: string;
}

interface PortConnectionHints {
  upstream: Record<string, PortNeighbor[]>;
  downstream: Record<string, PortNeighbor[]>;
}

const fallbackPortColors = {
  in: '#2563eb',
  out: '#0f766e',
};

function edgeSourceHandle(edge: Record<string, unknown>): string {
  return String(edge.source_handle || edge.sourceHandle || '');
}

function edgeTargetHandle(edge: Record<string, unknown>): string {
  return String(edge.target_handle || edge.targetHandle || '');
}

function atomTypeLabel(atom: Record<string, unknown> | undefined, fallbackId: string): string {
  if (!atom) return fallbackId;
  return String(atom.atom_type || atom.operation || atom.id || fallbackId);
}

function atomCategory(atom: Record<string, unknown> | undefined): string {
  return String(atom?.category || 'default');
}

function neighborForAtom(atom: Record<string, unknown> | undefined, fallbackId: string): PortNeighbor {
  const category = atomCategory(atom);
  return {
    id: String(atom?.id || fallbackId),
    atomType: atomTypeLabel(atom, fallbackId),
    category,
    color: nodeColors[category] || '#525252',
  };
}

function buildPortConnectionHints(atoms: Array<Record<string, unknown>>, edges: Array<Record<string, unknown>>) {
  const atomById = new Map(atoms.map((atom) => [String(atom.id), atom]));
  const hints = new Map<string, PortConnectionHints>();

  atoms.forEach((atom) => {
    hints.set(String(atom.id), { upstream: {}, downstream: {} });
  });

  edges.forEach((edge) => {
    const sourceId = String(edge.source || '');
    const targetId = String(edge.target || '');
    if (!sourceId || !targetId) return;

    const sourceAtom = atomById.get(sourceId);
    const targetAtom = atomById.get(targetId);
    const sourcePort = findPort(sourceAtom, edgeSourceHandle(edge), 'out');
    const targetPort = findPort(targetAtom, edgeTargetHandle(edge), 'in');
    const sourcePortName = String(edgeSourceHandle(edge) || sourcePort?.name || 'output');
    const targetPortName = String(edgeTargetHandle(edge) || targetPort?.name || 'input');

    const sourceHints = hints.get(sourceId);
    if (sourceHints) {
      sourceHints.downstream[sourcePortName] = [
        ...(sourceHints.downstream[sourcePortName] || []),
        neighborForAtom(targetAtom, targetId),
      ];
    }

    const targetHints = hints.get(targetId);
    if (targetHints) {
      targetHints.upstream[targetPortName] = [
        ...(targetHints.upstream[targetPortName] || []),
        neighborForAtom(sourceAtom, sourceId),
      ];
    }
  });

  return hints;
}

function portCount(atom: Record<string, unknown>, key: string, fallback: string) {
  return asRecords(atom[key]).length || asRecords(atom[fallback]).length || getAtomPorts(atom).filter((port) =>
    key === 'input_ports' ? port.direction === 'in' : port.direction === 'out'
  ).length;
}

function portHandleColor(neighbors: PortNeighbor[], direction: 'in' | 'out'): string {
  return neighbors[0]?.color || fallbackPortColors[direction];
}

function portHandleStyle(top: string, color: string, connected: boolean): CSSProperties {
  return {
    top,
    backgroundColor: color,
    boxShadow: connected ? `0 0 0 1px #fff, 0 0 0 3px ${color}` : `0 0 0 1px ${color}`,
  };
}

function portHandleTitle(
  port: { name: string; direction: 'in' | 'out'; schema: string },
  neighbors: PortNeighbor[]
): string {
  const directionLabel = port.direction === 'in' ? 'in' : 'out';
  const base = `${directionLabel} ${port.name}: ${port.schema}`;
  if (neighbors.length === 0) return `${base} - not connected`;
  const relation = port.direction === 'in' ? 'from' : 'to';
  const neighborLabels = neighbors.map((neighbor) => `${neighbor.atomType} (${neighbor.category})`).join(', ');
  return `${base} - ${relation} ${neighborLabels}`;
}

function NodeLabel({
  atom,
  missingInputs,
  emptyAtom,
  focused,
  portConnectionHints,
}: {
  atom: Record<string, unknown>;
  missingInputs: boolean;
  emptyAtom: boolean;
  focused: boolean;
  portConnectionHints: PortConnectionHints;
}) {
  const category = String(atom.category || 'node');
  const atomType = String(atom.atom_type || atom.id || 'Atom');
  const operation = String(atom.operation || atomType);
  const Icon = categoryIcons[category] || CircleDot;
  const inputPorts = getAtomPorts(atom).filter((port) => port.direction === 'in');
  const outputPorts = getAtomPorts(atom).filter((port) => port.direction === 'out');
  const handleTop = (index: number, total: number) => `${((index + 1) * 100) / (total + 1)}%`;

  return (
    <div className="flow-node-card">
      {inputPorts.map((port, index) => (
        (() => {
          const neighbors = portConnectionHints.upstream[port.name] || [];
          const color = portHandleColor(neighbors, 'in');
          return (
            <Handle
              key={`in-${port.name}`}
              type="target"
              id={port.name}
              position={Position.Left}
              className={`flow-port-handle flow-port-handle-in ${neighbors.length > 0 ? 'connected' : ''}`}
              style={portHandleStyle(handleTop(index, inputPorts.length), color, neighbors.length > 0)}
              title={portHandleTitle(port, neighbors)}
            />
          );
        })()
      ))}
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
      {outputPorts.map((port, index) => (
        (() => {
          const neighbors = portConnectionHints.downstream[port.name] || [];
          const color = portHandleColor(neighbors, 'out');
          return (
            <Handle
              key={`out-${port.name}`}
              type="source"
              id={port.name}
              position={Position.Right}
              className={`flow-port-handle flow-port-handle-out ${neighbors.length > 0 ? 'connected' : ''}`}
              style={portHandleStyle(handleTop(index, outputPorts.length), color, neighbors.length > 0)}
              title={portHandleTitle(port, neighbors)}
            />
          );
        })()
      ))}
    </div>
  );
}

function toNodes(flow: Record<string, unknown>, focusedAtomId?: string | null): Node[] {
  const flowAtoms = asRecords(flow.flow_atoms);
  const connectionHints = buildPortConnectionHints(flowAtoms, asRecords(flow.edges));
  return flowAtoms.map((atom) => ({
    ...(() => {
      const metadata = (atom.metadata as Record<string, unknown>) || {};
      const emptyAtom = atom.operation === 'empty_marker' || atom.atom_type === 'empty_marker' || metadata.empty_atom === true;
      const missingInputs = getAtomInputStatuses(flow, atom).some((input) => input.required && !input.connected);
      const focused = String(atom.id) === String(focusedAtomId || '');
      return {
        id: String(atom.id),
        type: 'flowAtom',
        position: (atom.position as { x: number; y: number }) ?? { x: 0, y: 0 },
        data: {
          label: (
            <NodeLabel
              atom={atom}
              missingInputs={missingInputs}
              emptyAtom={emptyAtom}
              focused={focused}
              portConnectionHints={connectionHints.get(String(atom.id)) || { upstream: {}, downstream: {} }}
            />
          ),
        },
        style: {
          background: 'transparent',
          border: 'none',
          boxShadow: 'none',
          padding: 0,
          cursor: 'pointer',
        },
        className: `flow-node flow-node-${String(atom.category || 'default')} ${missingInputs ? 'flow-node-missing-inputs' : ''} ${emptyAtom ? 'flow-node-empty' : ''} ${focused ? 'flow-node-focused' : ''}`,
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      };
    })(),
  }));
}

export function FlowCanvas({
  flow,
  onChange,
  readOnly = false,
  focusedAtomId,
  activeChecklistStep,
  onInspectingChange,
}: FlowCanvasProps) {
  const project = useStore((s) => s.project);
  const processedHb = ((flow.data_semantics as Record<string, unknown>) || {}).branch === 'vendor_processed_hb';
  const [nodes, setNodes] = useNodesState([]);
  const [edges, setEdges] = useEdgesState([]);
  const [selectedNode, setSelectedNode] = useState<NodeDetail | null>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);
  const [connectionError, setConnectionError] = useState('');
  const [canvasNotice, setCanvasNotice] = useState('');
  const [emptyMarkerSpecs, setEmptyMarkerSpecs] = useState<EmptyMarkerSpec[]>([]);
  const [atomTemplates, setAtomTemplates] = useState<AtomTemplate[]>([]);
  const [emptyRemovalPreview, setEmptyRemovalPreview] = useState<ReturnType<typeof previewEmptyRiskRemoval> | null>(null);
  const closeEmptyRemovalPreview = useCallback(() => setEmptyRemovalPreview(null), []);
  const emptyRemovalDialogRef = useModalDialog(emptyRemovalPreview !== null, closeEmptyRemovalPreview);
  const [searchParams] = useSearchParams();
  const nodesRef = useRef<Node[]>([]);
  const edgesRef = useRef<Edge[]>([]);
  const nodeCount = nodes.length;
  const edgeCount = edges.length;
  const loadProjectFolders = useCallback(async (parent: string) => {
    if (!project?.id) return [];
    const result = await listProjectDataFolders(project.id, parent);
    return result.folders;
  }, [project?.id]);

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
    listAtomTemplates()
      .then(setAtomTemplates)
      .catch(() => setAtomTemplates([]));
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
    const detail = selectAtomDetail(flow, nodeId, atomTemplates);
    if (detail) {
      setSelectedNode(detail);
      onInspectingChange?.(true);
    }
  }, [atomTemplates, flow, onInspectingChange, searchParams]);

  useEffect(() => {
    if (!focusedAtomId) return;
    const atom = flowAtoms.find((item) => String(item.id) === focusedAtomId);
    const detail = selectAtomDetail(flow, focusedAtomId, atomTemplates);
    if (!atom || !detail) return;
    setSelectedNode(detail);
    onInspectingChange?.(true);
    const position = (atom.position as { x: number; y: number }) || undefined;
    if (position && reactFlowInstance) {
      reactFlowInstance.setCenter(position.x + 90, position.y + 40, { zoom: 1, duration: 300 });
    }
  }, [atomTemplates, flow, flowAtoms, focusedAtomId, onInspectingChange, reactFlowInstance]);

  useEffect(() => {
    if (!selectedNode || atomTemplates.length === 0) return;
    const atom = flowAtoms.find((item) => String(item.id) === selectedNode.id);
    if (!atom) return;
    const nextDetail = atomToDetailWithDefaults(atom, atomTemplates);
    const currentKeys = Object.keys(selectedNode.config);
    const nextKeys = Object.keys(nextDetail.config);
    if (currentKeys.length === 0 && nextKeys.length > 0) {
      setSelectedNode(nextDetail);
    }
  }, [atomTemplates, flowAtoms, selectedNode]);

  const onConnect = useCallback(
    (params: Connection) => {
      if (readOnly) return;
      if (processedHb) {
        const candidate = flowAtoms.find((atom) => String(atom.id) === String(params.target || ''));
        const operation = String(candidate?.operation || candidate?.atom_type || '');
        if (['optical_density', 'motion_correction', 'filtering', 'beer_lambert_law', 'mbll'].includes(operation)) {
          setConnectionError('Processed-Hb recordings cannot connect to raw-intensity preprocessing atoms.');
          return;
        }
      }
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
    [flow, flowAtoms, onChange, orderPolicy, processedHb, readOnly, setEdges]
  );

  const isValidConnection = useCallback(
    (connection: Connection) => {
      if (readOnly) return false;
      if (processedHb) {
        const candidate = flowAtoms.find((atom) => String(atom.id) === String(connection.target || ''));
        const operation = String(candidate?.operation || candidate?.atom_type || '');
        if (['optical_density', 'motion_correction', 'filtering', 'beer_lambert_law', 'mbll'].includes(operation)) return false;
      }
      return connectionProblem(connection, flowAtoms, edgesRef.current, orderPolicy) === null;
    },
    [flowAtoms, orderPolicy, processedHb, readOnly]
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
      const detail = selectAtomDetail(flow, node.id, atomTemplates);
      if (detail) {
        setSelectedNode(detail);
        onInspectingChange?.(true);
      }
    },
    [atomTemplates, flow, onInspectingChange]
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
    onInspectingChange?.(false);
  }, [onInspectingChange]);

  const deleteSelectedNode = useCallback(() => {
    if (readOnly || !selectedNode) return;
    const deleted = deleteAtomCommand(flow, selectedNode.id, nodesRef.current, edgesRef.current);
    const { nodes: nextNodes, edges: nextEdges } = deleted;
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
    setNodes(nextNodes);
    setEdges(nextEdges);
    setSelectedNode(null);
    onInspectingChange?.(false);
    onChange(deleted.flow);
  }, [flow, onChange, onInspectingChange, readOnly, selectedNode, setEdges, setNodes]);

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
      if (processedHb && !['frozen_manifest_discovery', 'read_vendor_processed_hb', 'ingest_frozen_events', 'regularize_processed_hb_time', 'compile_processed_hb_designs', 'fit_processed_hb_first_level', 'estimate_full_contrasts', 'write_processed_hb_derivatives'].includes(template.operation || template.id)) {
        setCanvasNotice('This atom is incompatible with the vendor processed-Hb branch.');
        return;
      }
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
        nextFlow = { ...nextFlow, [atomKey]: nextAtoms };
        nextFlow = withChecklistChoice(nextFlow, activeChecklistStep.scenarioId, activeChecklistStep.slotId, {
          template_id: template.id,
          atom_id: String(added.atom.id),
          skipped: false,
        });
      }
      onChange(nextFlow);
    },
    [activeChecklistStep, flow, onChange, processedHb, reactFlowInstance, readOnly]
  );

  return (
    <div className="flow-canvas-shell">
      <div className="flow-canvas-stage" onDragOver={onDragOver} onDrop={onDrop}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
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
          <div
            ref={emptyRemovalDialogRef}
            className="canvas-empty-removal-preview"
            role="dialog"
            aria-modal="true"
            aria-labelledby="empty-removal-title"
            aria-describedby="empty-removal-description"
            tabIndex={-1}
          >
            <strong id="empty-removal-title">Disable Empty risk?</strong>
            <span id="empty-removal-description">
              Remove {emptyRemovalPreview.removed_atoms.length} empty atom{emptyRemovalPreview.removed_atoms.length === 1 ? '' : 's'}
              {emptyRemovalPreview.cleared_slots.length > 0 ? ` and clear ${emptyRemovalPreview.cleared_slots.length} skip marker${emptyRemovalPreview.cleared_slots.length === 1 ? '' : 's'}` : ''}.
            </span>
            <div>
              <button className="icon-text-button" onClick={applyEmptyRemoval} type="button">Apply</button>
              <button className="icon-text-button subtle" onClick={closeEmptyRemovalPreview} type="button">Cancel</button>
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
              <h4>Ports: in / out</h4>
              {selectedNode.ports.map((port) => (
                <div key={`${port.direction}-${port.name}`} className={`port-row port-row-${port.direction}`}>
                  <span className={`port-dot ${port.direction}`} />
                  <span className={`port-direction-badge ${port.direction}`}>{port.direction}</span>
                  <span>{port.name}</span>
                  <code>{port.schema}</code>
                </div>
              ))}
            </section>
          )}
          <ParameterPanel
            title="Parameters"
            parameters={visibleParameterEntries(selectedNode).map(([name, value]) => {
              const spec = parameterSpecForNode(name, selectedNode, atomTemplates);
              return {
                name,
                type: String(spec.type || parameterTypeForValue(value)),
                value,
                control: typeof spec.control === 'string' ? spec.control : undefined,
                description: typeof spec.description === 'string' ? spec.description : undefined,
                placeholder: typeof spec.placeholder === 'string' ? spec.placeholder : undefined,
                advanced: spec.advanced === true,
                source: typeof spec.source === 'string' ? spec.source : undefined,
                options: parameterOptionsForNode(name, value, selectedNode, atomTemplates),
                enum: Array.isArray(spec.enum) ? spec.enum : undefined,
                minimum: typeof spec.minimum === 'number' ? spec.minimum : undefined,
                maximum: typeof spec.maximum === 'number' ? spec.maximum : undefined,
                min: typeof spec.min === 'number' ? spec.min : undefined,
                max: typeof spec.max === 'number' ? spec.max : undefined,
                range: Array.isArray(spec.range) || (spec.range && typeof spec.range === 'object')
                  ? spec.range as [number, number] | { min?: number; max?: number; minimum?: number; maximum?: number }
                  : undefined,
              };
            })}
            onChange={(name, value) => {
              if (readOnly) return;
              const updatedConfig = { ...selectedNode.config, [name]: value };
              const nextReadiness = selectedNode.readiness_status === 'not_configured'
                ? 'configured'
                : selectedNode.readiness_status;
              setSelectedNode({ ...selectedNode, config: updatedConfig, readiness_status: nextReadiness });
              const nextAtoms = asRecords(flow.flow_atoms).map((atom) =>
                String(atom.id) === selectedNode.id
                  ? { ...atom, config: updatedConfig, readiness_status: nextReadiness }
                  : atom
              );
              onChange({
                ...flow,
                flow_atoms: nextAtoms,
              });
            }}
            onBulkChange={(values) => {
              if (readOnly) return;
              const updatedConfig = { ...selectedNode.config, ...values };
              const nextReadiness = selectedNode.readiness_status === 'not_configured'
                ? 'configured'
                : selectedNode.readiness_status;
              setSelectedNode({ ...selectedNode, config: updatedConfig, readiness_status: nextReadiness });
              const nextAtoms = asRecords(flow.flow_atoms).map((atom) =>
                String(atom.id) === selectedNode.id
                  ? { ...atom, config: updatedConfig, readiness_status: nextReadiness }
                  : atom
              );
              onChange({
                ...flow,
                flow_atoms: nextAtoms,
              });
            }}
            atomInfo={{
              atom_id: selectedNode.id,
              atom_type: selectedNode.atom_type,
              operation: selectedNode.operation,
              readiness_status: selectedNode.readiness_status,
            }}
            loadProjectFolders={project?.data_root ? loadProjectFolders : undefined}
          />
        </aside>
      )}
    </div>
  );
}
