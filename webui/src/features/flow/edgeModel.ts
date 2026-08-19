import type { Edge, EdgeChange } from 'reactflow';
import { asRecords, findPort } from '../../flow/atomFactory.ts';

export function toCanvasEdges(flow: Record<string, unknown>): Edge[] {
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

export function serializeCanvasEdges(
  flowAtoms: Array<Record<string, unknown>>,
  edges: Edge[],
): Array<Record<string, unknown>> {
  const atomById = new Map(flowAtoms.map((atom) => [String(atom.id), atom]));
  return edges.map((edge, index) => {
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
}

export const shouldSyncEdgeChanges = (changes: EdgeChange[]) =>
  changes.some((change) => change.type === 'remove');
