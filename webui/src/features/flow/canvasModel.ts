import type { Edge, Node, NodeChange } from 'reactflow';
import { asRecords } from '../../flow/atomFactory.ts';
import { serializeCanvasEdges } from './edgeModel.ts';

export function syncCanvasFlow(
  flow: Record<string, unknown>,
  nodes: Node[],
  edges: Edge[],
): Record<string, unknown> {
  const existingAtoms = asRecords(flow.flow_atoms);
  const atomById = new Map(existingAtoms.map((atom) => [String(atom.id), atom]));
  const nextAtoms = nodes.map((node) => ({
    ...(atomById.get(String(node.id)) || { id: String(node.id), type: String(node.id) }),
    id: String(node.id),
    position: node.position,
  }));
  const nextEdges = serializeCanvasEdges(existingAtoms, edges);
  return { ...flow, flow_atoms: nextAtoms, edges: nextEdges };
}

export const shouldSyncNodeChanges = (changes: NodeChange[]) =>
  changes.some((change) => ['position', 'remove'].includes(change.type));
