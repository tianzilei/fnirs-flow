export type FlowPayload = Record<string, unknown> & {
  schema_version?: string;
  flow_atoms?: unknown[];
  nodes?: unknown[];
};

export function normalizeFlowPayload(payload: FlowPayload): FlowPayload {
  const source = Array.isArray(payload.flow_atoms)
    ? payload.flow_atoms
    : Array.isArray(payload.nodes)
      ? payload.nodes
      : [];
  const flow_atoms = source.map((value) => {
    if (!value || typeof value !== 'object') return value;
    const atom = { ...(value as Record<string, unknown>) };
    if (!atom.atom_type && atom.type) atom.atom_type = atom.type;
    delete atom.type;
    return atom;
  });
  const normalized = { ...payload, schema_version: payload.schema_version ?? '0.4.0', flow_atoms };
  delete normalized.nodes;
  return normalized;
}

export function serializeFlowPayload(payload: FlowPayload, schemaVersion = '0.4.0'): FlowPayload {
  const canonical = normalizeFlowPayload(payload);
  if (schemaVersion === '0.1.0') {
    const nodes = (canonical.flow_atoms ?? []).map((value) => {
      if (!value || typeof value !== 'object') return value;
      const atom = { ...(value as Record<string, unknown>) };
      atom.type = atom.atom_type;
      return atom;
    });
    const legacy = { ...canonical, schema_version: schemaVersion, nodes };
    delete legacy.flow_atoms;
    return legacy;
  }
  return { ...canonical, schema_version: schemaVersion };
}
