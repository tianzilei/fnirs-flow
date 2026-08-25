import assert from 'node:assert/strict';
import test from 'node:test';
import { deleteAtomCommand } from '../src/features/flow/commands.ts';
import { selectAtomDetail } from '../src/features/flow/selectionModel.ts';
import { makeCanonicalFlow } from './fixtures.ts';

test('selection model resolves canonical flow atoms', () => {
  const flow = makeCanonicalFlow();
  const detail = selectAtomDetail(flow, 'b', []);
  assert.equal(detail?.atom_type, 'optical_density');
  assert.equal(selectAtomDetail(flow, 'missing', []), null);
});

test('delete command removes the atom and connected edges atomically', () => {
  const flow = makeCanonicalFlow();
  const result = deleteAtomCommand(
    flow,
    'a',
    [{ id: 'a', position: { x: 0, y: 0 }, data: {} }, { id: 'b', position: { x: 1, y: 0 }, data: {} }],
    [{ id: 'a-b', source: 'a', target: 'b' }],
  );
  assert.deepEqual(result.nodes.map((node) => node.id), ['b']);
  assert.deepEqual(result.edges, []);
  assert.deepEqual((result.flow.flow_atoms as Array<{ id: string }>).map((atom) => atom.id), ['b']);
});
