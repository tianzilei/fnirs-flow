import type { AtomTemplate } from '../../api/client';
import { flowAtoms } from '../../flow/atomFactory.ts';
import { atomToDetailWithDefaults, type NodeDetail } from './nodeModel.ts';

export function selectAtomDetail(
  flow: Record<string, unknown>,
  atomId: string | null | undefined,
  templates: AtomTemplate[],
): NodeDetail | null {
  if (!atomId) return null;
  const atom = flowAtoms(flow).find((item) => String(item.id) === String(atomId));
  return atom ? atomToDetailWithDefaults(atom, templates) : null;
}
