type TestParameter = {
  name: string;
  type: string;
  value: unknown;
};

export function makeParameters(): TestParameter[] {
  return [
    { name: 'enabled', type: 'boolean', value: false },
    { name: 'alpha', type: 'number', value: 0.05 },
    { name: 'channels', type: 'number-list', value: [1, 2] },
    { name: 'metadata', type: 'text', value: { group: 'control' } },
    { name: 'label', type: 'text', value: 'baseline' },
  ];
}

export function makeCanonicalFlow() {
  return {
    schema_version: '0.3.0',
    flow_atoms: [
      { id: 'a', atom_type: 'read_run', operation: 'read_run', category: 'data', config: {}, position: { x: 0, y: 0 } },
      { id: 'b', atom_type: 'optical_density', operation: 'optical_density', category: 'preprocessing', config: {}, position: { x: 1, y: 0 } },
    ],
    edges: [{ id: 'a-b', source: 'a', target: 'b', source_handle: 'out', target_handle: 'in' }],
  };
}
