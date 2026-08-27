import assert from 'node:assert/strict';
import test from 'node:test';
import type { StoreState } from '../src/store/types.ts';
import { selectProjectStatus } from '../src/features/project/projectStatus.ts';

test('project status keeps the empty quarantine snapshot stable', () => {
  const state = {
    project: null,
    flow: {},
    validation: null,
    compileResult: null,
    discoverResult: null,
    executeInfo: null,
    readiness: null,
  } as StoreState;
  const first = selectProjectStatus(state);
  const second = selectProjectStatus(state);

  assert.strictEqual(first.quarantinedAtoms, second.quarantinedAtoms);
  assert.deepEqual(first.quarantinedAtoms, []);
});
