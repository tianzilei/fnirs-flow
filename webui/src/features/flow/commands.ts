import type { Edge, Node } from 'reactflow';
import { clearChecklistChoiceForAtom, flowAtoms } from '../../flow/atomFactory.ts';
import { syncCanvasFlow } from './canvasModel.ts';

export interface DeleteAtomResult {
  flow: Record<string, unknown>;
  nodes: Node[];
  edges: Edge[];
}

export function deleteAtomCommand(
  flow: Record<string, unknown>,
  atomId: string,
  nodes: Node[],
  edges: Edge[],
): DeleteAtomResult {
  const removedAtom = flowAtoms(flow).find((atom) => String(atom.id) === atomId);
  const nextNodes = nodes.filter((node) => node.id !== atomId);
  const nextEdges = edges.filter((edge) => edge.source !== atomId && edge.target !== atomId);
  const synced = syncCanvasFlow(flow, nextNodes, nextEdges);
  return {
    nodes: nextNodes,
    edges: nextEdges,
    flow: removedAtom ? clearChecklistChoiceForAtom(synced, removedAtom) : synced,
  };
}
