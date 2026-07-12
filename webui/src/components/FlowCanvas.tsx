import { useCallback, useEffect, useMemo, useState } from 'react';
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
import 'reactflow/dist/style.css';
import type { AtomTemplate } from '../api/client';
import { ParameterPanel } from './ParameterPanel';

interface FlowCanvasProps {
  flow: Record<string, unknown>;
  onChange: (flow: Record<string, unknown>) => void;
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
  config: Record<string, unknown>;
  parameters: Record<string, unknown>;
  ports: Array<{ name: string; direction: string; schema: string }>;
}

function asRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

function portCount(atom: Record<string, unknown>, key: string, fallback: string) {
  return asRecords(atom[key]).length || asRecords(atom[fallback]).length;
}

function NodeLabel({ atom }: { atom: Record<string, unknown> }) {
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
    </div>
  );
}

function toNodes(flow: Record<string, unknown>): Node[] {
  const flowAtoms = asRecords(flow.flow_atoms).length > 0 ? asRecords(flow.flow_atoms) : asRecords(flow.nodes);
  return flowAtoms.map((atom) => ({
    id: String(atom.id),
    position: (atom.position as { x: number; y: number }) ?? { x: 0, y: 0 },
    data: { label: <NodeLabel atom={atom} /> },
    style: {
      background: 'transparent',
      border: 'none',
      boxShadow: 'none',
      padding: 0,
      cursor: 'pointer',
    },
    className: `flow-node flow-node-${String(atom.category || 'default')}`,
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
  const nextEdges = edges.map((edge, index) => ({
    id: String(edge.id || `edge-${index + 1}`),
    source: String(edge.source),
    target: String(edge.target),
    source_handle: String(edge.sourceHandle || 'output'),
    target_handle: String(edge.targetHandle || 'input'),
  }));
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
  const inputPorts = asRecords(atom.input_ports).map((port) => ({
    name: String(port.name || 'input'),
    direction: 'in',
    schema: String(port.schema || port.type || 'unknown'),
  }));
  const outputPorts = asRecords(atom.output_ports).map((port) => ({
    name: String(port.name || 'output'),
    direction: 'out',
    schema: String(port.schema || port.type || 'unknown'),
  }));
  const legacyPorts = asRecords(atom.ports).map((port) => ({
    name: String(port.name || 'port'),
    direction: String(port.direction || 'in'),
    schema: String(port.schema || 'unknown'),
  }));
  return [...inputPorts, ...outputPorts, ...legacyPorts];
}

export function FlowCanvas({ flow, onChange }: FlowCanvasProps) {
  const [nodes, setNodes] = useNodesState([]);
  const [edges, setEdges] = useEdgesState([]);
  const [selectedNode, setSelectedNode] = useState<NodeDetail | null>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);
  const nodeCount = nodes.length;
  const edgeCount = edges.length;

  useEffect(() => {
    setNodes(toNodes(flow));
    setEdges(toEdges(flow));
  }, [flow, setNodes, setEdges]);

  const flowAtoms = useMemo(
    () => (asRecords(flow.flow_atoms).length > 0 ? asRecords(flow.flow_atoms) : asRecords(flow.nodes)),
    [flow]
  );

  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((currentEdges) => {
        const nextEdges = addEdge({ ...params, animated: true, className: 'flow-edge' }, currentEdges);
        onChange(syncFlow(flow, nodes, nextEdges));
        return nextEdges;
      });
    },
    [flow, nodes, onChange, setEdges]
  );

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setNodes((currentNodes) => {
        const nextNodes = applyNodeChanges(changes, currentNodes);
        if (shouldSyncNodeChanges(changes)) {
          onChange(syncFlow(flow, nextNodes, edges));
        }
        return nextNodes;
      });
    },
    [edges, flow, onChange, setNodes]
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setEdges((currentEdges) => {
        const nextEdges = applyEdgeChanges(changes, currentEdges);
        if (shouldSyncEdgeChanges(changes)) {
          onChange(syncFlow(flow, nodes, nextEdges));
        }
        return nextEdges;
      });
    },
    [nodes, flow, onChange, setEdges]
  );

  const onNodeClick: NodeMouseHandler = useCallback(
    (_, node) => {
      const atom = flowAtoms.find((item) => String(item.id) === node.id);
      if (atom) {
        setSelectedNode({
          id: String(atom.id),
          atom_type: String(atom.atom_type || atom.type || ''),
          operation: String(atom.operation || ''),
          category: String(atom.category || ''),
          config: (atom.config as Record<string, unknown>) || {},
          parameters: (atom.parameters as Record<string, unknown>) || {},
          ports: normalizePorts(atom),
        });
      }
    },
    [flowAtoms]
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      if (!reactFlowInstance) return;

      const payload = event.dataTransfer.getData('application/atom-template');
      if (!payload) return;

      const template = JSON.parse(payload) as AtomTemplate;
      const bounds = (event.currentTarget as HTMLDivElement).getBoundingClientRect();
      const position = reactFlowInstance.project({
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      });
      const baseId = template.operation || template.atom_type || template.id;
      const existingIds = new Set(nodes.map((node) => node.id));
      let index = nodes.length + 1;
      let id = `${baseId}_${index}`;
      while (existingIds.has(id)) {
        index += 1;
        id = `${baseId}_${index}`;
      }

      const atom = {
        id,
        atom_id: id,
        atom_type: template.atom_type,
        type: template.atom_type,
        template_id: template.id,
        category: template.category,
        operation: template.operation,
        description: template.description,
        input_ports: template.input_ports,
        output_ports: template.output_ports,
        evidence_refs: template.evidence_refs,
        parameters: {},
        config: {},
        position,
      };
      const atomKey = Array.isArray(flow.flow_atoms) ? 'flow_atoms' : 'nodes';
      const nextAtoms = [...asRecords(flow[atomKey]), atom];
      const nextFlow = {
        ...flow,
        [atomKey]: nextAtoms,
        ...(atomKey === 'flow_atoms' && Array.isArray(flow.nodes) ? { nodes: nextAtoms } : {}),
      };
      onChange(nextFlow);
    },
    [flow, nodes, onChange, reactFlowInstance]
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
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onInit={setReactFlowInstance}
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
              // Update the atom's parameters in the flow
              const updatedParams = { ...selectedNode.parameters, [name]: value };
              setSelectedNode({ ...selectedNode, parameters: updatedParams });
            }}
            atomInfo={{
              atom_id: selectedNode.id,
              atom_type: selectedNode.atom_type,
              operation: selectedNode.operation,
            }}
          />
        </aside>
      )}
    </div>
  );
}
