import type { Connection, Edge } from 'reactflow';
import type { AtomTemplate, EmptyMarkerSpec, FlowChecklist, FlowChecklistStep } from '../api/client';

export interface AtomPortRecord {
  name: string;
  direction: 'in' | 'out';
  schema: string;
  required: boolean;
}

export interface OrderPolicy {
  allow_order_violations?: boolean;
  allow_empty_edges?: boolean;
}

export interface ChecklistChoice {
  template_id?: string;
  skipped?: boolean;
  skip_reason?: string;
  atom_id?: string;
  updated_at?: string;
}

export type ChecklistRecommendationTier = 'best' | 'recommended' | 'alternative' | 'off_path';

export interface ChecklistTemplateRecommendation {
  template_id: string;
  tier: ChecklistRecommendationTier;
}

export interface AtomInputStatus {
  name: string;
  schema: string;
  required: boolean;
  connected: boolean;
  source_atom_id?: string;
  source_handle?: string;
}

export interface ConnectSkippedInput {
  target_atom_id: string;
  target_input: string;
  schema: string;
  reason: string;
}

export interface ConnectReport {
  flow: Record<string, unknown>;
  connected_edges: Array<Record<string, unknown>>;
  skipped_inputs: ConnectSkippedInput[];
}

export interface ChecklistAddedAtom {
  slot_id: string;
  atom_id: string;
  template_id: string;
  label: string;
}

export interface ChecklistBuildPreview extends ConnectReport {
  added_atoms: ChecklistAddedAtom[];
}

export interface EmptyRiskRemovalPreview {
  flow: Record<string, unknown>;
  removed_atoms: Array<{ atom_id: string; category: string; slot_id?: string; skip_reason?: string }>;
  cleared_slots: string[];
}

export const categoryOrder: Record<string, number> = {
  data: 0,
  design: 1,
  preprocessing: 2,
  analysis: 3,
  output: 4,
  validation: 5,
  export: 6,
};

export function asRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

export function atomCollectionKey(flow: Record<string, unknown>): 'flow_atoms' | 'nodes' {
  return Array.isArray(flow.flow_atoms) ? 'flow_atoms' : 'nodes';
}

export function flowAtoms(flow: Record<string, unknown>): Array<Record<string, unknown>> {
  return asRecords(flow.flow_atoms).length > 0 ? asRecords(flow.flow_atoms) : asRecords(flow.nodes);
}

export function getOrderPolicy(flow: Record<string, unknown>): OrderPolicy {
  const metadata = (flow.metadata as Record<string, unknown>) || {};
  return ((metadata.order_policy as OrderPolicy) || {}) as OrderPolicy;
}

export function withOrderPolicy(flow: Record<string, unknown>, patch: OrderPolicy): Record<string, unknown> {
  const metadata = (flow.metadata as Record<string, unknown>) || {};
  const previous = ((metadata.order_policy as OrderPolicy) || {}) as OrderPolicy;
  return {
    ...flow,
    metadata: {
      ...metadata,
      order_policy: {
        ...previous,
        ...patch,
      },
    },
  };
}

export function withChecklistMetadata(
  flow: Record<string, unknown>,
  scenarioId: string,
  patch: Record<string, unknown> = {}
): Record<string, unknown> {
  const metadata = (flow.metadata as Record<string, unknown>) || {};
  const previous = ((metadata.checklist as Record<string, unknown>) || {}) as Record<string, unknown>;
  return {
    ...flow,
    metadata: {
      ...metadata,
      checklist: {
        ...previous,
        scenario_id: scenarioId,
        updated_at: new Date().toISOString(),
        ...patch,
      },
    },
  };
}

export function getChecklistChoices(flow: Record<string, unknown>): Record<string, ChecklistChoice> {
  const metadata = (flow.metadata as Record<string, unknown>) || {};
  const checklist = ((metadata.checklist as Record<string, unknown>) || {}) as Record<string, unknown>;
  return ((checklist.choices as Record<string, ChecklistChoice>) || {}) as Record<string, ChecklistChoice>;
}

export function getChecklistMetadata(flow: Record<string, unknown>): Record<string, unknown> {
  const metadata = (flow.metadata as Record<string, unknown>) || {};
  return ((metadata.checklist as Record<string, unknown>) || {}) as Record<string, unknown>;
}

export function inferChecklistScenario(flow: Record<string, unknown>): string {
  const templateIds = new Set(
    flowAtoms(flow).flatMap((atom) => [
      atomTemplateId(atom),
      String(atom.operation || ''),
      String(atom.atom_type || atom.type || ''),
    ])
  );
  const hasAny = (...ids: string[]) => ids.some((id) => templateIds.has(id));
  if (hasAny('ml_model', 'svm_model', 'lda_model', 'cross_validation', 'feature_extraction', 'ml_classification')) {
    return 'ml_classification';
  }
  if (hasAny('connectivity_analysis', 'plv_connectivity', 'coherence_connectivity', 'wtc_connectivity', 'resting_connectivity')) {
    return 'resting_state_connectivity';
  }
  if (hasAny('participant_table_input', 'participant_metadata_validate', 'group_design_matrix', 'linear_mixed_effects_glm', 'site_covariate_glm')) {
    return 'group_analysis';
  }
  return 'task_glm';
}

export function withChecklistChoice(
  flow: Record<string, unknown>,
  scenarioId: string,
  slotId: string,
  choice: ChecklistChoice
): Record<string, unknown> {
  const choices = getChecklistChoices(flow);
  return withChecklistMetadata(flow, scenarioId, {
    choices: {
      ...choices,
      [slotId]: {
        ...(choices[slotId] || {}),
        ...choice,
        updated_at: new Date().toISOString(),
      },
    },
  });
}

export function clearChecklistChoiceForAtom(
  flow: Record<string, unknown>,
  atom: Record<string, unknown>
): Record<string, unknown> {
  const metadata = (atom.metadata as Record<string, unknown>) || {};
  const removedAtomId = String(atom.id || '');
  const slotFromAtom = metadata.checklist_slot_id ? String(metadata.checklist_slot_id) : '';
  const checklist = getChecklistMetadata(flow);
  const choices = getChecklistChoices(flow);
  if (!checklist.scenario_id || Object.keys(choices).length === 0) return flow;

  const nextChoices = Object.fromEntries(
    Object.entries(choices).map(([slotId, choice]) => {
      const linkedToRemovedAtom = choice.atom_id === removedAtomId || slotId === slotFromAtom;
      if (!linkedToRemovedAtom) return [slotId, choice];
      const { atom_id: _atomId, skipped: _skipped, skip_reason: _skipReason, ...rest } = choice;
      return [slotId, rest];
    })
  );
  return withChecklistMetadata(flow, String(checklist.scenario_id), { choices: nextChoices });
}

export function normalizePortRecord(port: Record<string, unknown>, direction?: 'in' | 'out'): AtomPortRecord {
  return {
    name: String(port.name || (direction === 'out' ? 'output' : 'input')),
    direction: direction || (String(port.direction || 'in') === 'out' ? 'out' : 'in'),
    schema: String(port.schema || port.port_schema || port.type || 'unknown'),
    required: port.required !== false,
  };
}

export function getAtomPorts(atom: Record<string, unknown>): AtomPortRecord[] {
  const ports = asRecords(atom.ports);
  if (ports.length > 0) {
    return ports.map((port) => normalizePortRecord(port));
  }
  return [
    ...asRecords(atom.input_ports).map((port) => normalizePortRecord(port, 'in')),
    ...asRecords(atom.output_ports).map((port) => normalizePortRecord(port, 'out')),
  ];
}

export function findPort(
  atom: Record<string, unknown> | undefined,
  handle: string | null | undefined,
  direction: 'in' | 'out'
): AtomPortRecord | undefined {
  if (!atom) return undefined;
  const ports = getAtomPorts(atom).filter((port) => port.direction === direction);
  if (handle) {
    return ports.find((port) => port.name === handle) || ports[0];
  }
  return ports[0];
}

function edgeTargetHandle(edge: Record<string, unknown>): string {
  return String(edge.target_handle || edge.targetHandle || '');
}

function edgeSourceHandle(edge: Record<string, unknown>): string {
  return String(edge.source_handle || edge.sourceHandle || '');
}

export function atomTemplateId(atom: Record<string, unknown>) {
  const metadata = (atom.metadata as Record<string, unknown>) || {};
  return String(atom.template_id || metadata.template_id || '');
}

export function atomMatchesChecklistStep(atom: Record<string, unknown>, step: FlowChecklistStep) {
  const templateId = atomTemplateId(atom);
  const atomType = String(atom.atom_type || atom.type || '');
  const operation = String(atom.operation || '');
  return (
    step.recommended_template_ids.includes(templateId) ||
    step.recommended_template_ids.includes(operation) ||
    step.recommended_atom_types.includes(atomType)
  );
}

export function checklistStepTemplateIds(step: FlowChecklistStep): string[] {
  return Array.from(new Set([
    step.default_template_id,
    ...step.recommended_template_ids,
    ...step.alternative_template_ids,
  ].filter(Boolean)));
}

export function checklistTemplateRecommendations(step: FlowChecklistStep): ChecklistTemplateRecommendation[] {
  return checklistStepTemplateIds(step).map((templateId) => {
    let tier: ChecklistRecommendationTier = 'alternative';
    if (templateId === step.default_template_id) tier = 'best';
    else if (step.recommended_template_ids.includes(templateId)) tier = 'recommended';
    return { template_id: templateId, tier };
  });
}

export function recommendationTierForTemplate(
  recommendations: ChecklistTemplateRecommendation[],
  template: Pick<AtomTemplate, 'id' | 'operation'>
): ChecklistRecommendationTier {
  return recommendations.find((item) => item.template_id === template.id || item.template_id === template.operation)?.tier || 'off_path';
}

export function recommendationReasonForTemplate(
  recommendations: ChecklistTemplateRecommendation[],
  template: Pick<AtomTemplate, 'id' | 'operation' | 'input_ports' | 'output_ports'>
): string {
  const tier = recommendationTierForTemplate(recommendations, template);
  if (tier === 'best') return 'Default for this step';
  if (tier === 'recommended') {
    const hasInputs = template.input_ports.length > 0;
    const hasOutputs = template.output_ports.length > 0;
    if (hasInputs && hasOutputs) return 'Matches this processing slot';
    if (hasInputs) return 'Consumes the expected input';
    if (hasOutputs) return 'Produces the expected output';
    return 'Recommended for this step';
  }
  if (tier === 'alternative') return 'Alternative path';
  return '';
}

export function connectSkipReasonText(reason: string): string {
  const labels: Record<string, string> = {
    already_connected: 'Already linked',
    no_upstream_atoms: 'Add an upstream atom first',
    schema_mismatch: 'Needs a matching output or adapter',
    upstream_not_allowed: 'Choose an earlier checklist atom',
    would_create_cycle: 'Would create a loop',
    order_policy_blocked: 'Blocked by order policy',
    no_schema_match: 'No compatible output found',
  };
  return labels[reason] || reason.replace(/_/g, ' ');
}

export function findChecklistStepTemplate(
  step: FlowChecklistStep,
  templates: AtomTemplate[],
  selectedId?: string
): AtomTemplate | undefined {
  return [selectedId, ...checklistStepTemplateIds(step)]
    .filter(Boolean)
    .map((id) => templates.find((item) => item.id === id || item.operation === id))
    .find(Boolean);
}

export function firstChecklistStepAtom(
  atoms: Array<Record<string, unknown>>,
  step: FlowChecklistStep
): Record<string, unknown> | undefined {
  return atoms.find((atom) => atomMatchesChecklistStep(atom, step));
}

export function getAtomInputStatuses(
  flow: Record<string, unknown>,
  atom: Record<string, unknown>
): AtomInputStatus[] {
  const atomById = new Map(flowAtoms(flow).map((item) => [String(item.id), item]));
  const targetId = String(atom.id);
  const edges = asRecords(flow.edges);
  return getAtomPorts(atom)
    .filter((port) => port.direction === 'in')
    .map((port) => {
      const edge = edges.find(
        (candidate) => String(candidate.target) === targetId && edgeTargetHandle(candidate) === port.name
      );
      if (!edge) {
        return {
          name: port.name,
          schema: port.schema,
          required: port.required,
          connected: false,
        };
      }
      const source = atomById.get(String(edge.source));
      return {
        name: port.name,
        schema: port.schema,
        required: port.required,
        connected: true,
        source_atom_id: source ? String(source.id) : String(edge.source || ''),
        source_handle: edgeSourceHandle(edge),
      };
    });
}

export function templatePorts(template: AtomTemplate): AtomPortRecord[] {
  if (template.ports && template.ports.length > 0) {
    return template.ports.map((port) => normalizePortRecord(port as unknown as Record<string, unknown>));
  }
  return [
    ...template.input_ports.map((port) => ({ ...port, direction: 'in' as const })),
    ...template.output_ports.map((port) => ({ ...port, direction: 'out' as const })),
  ];
}

export function createFlowAtomFromTemplate(template: AtomTemplate, id: string, position: { x: number; y: number }) {
  const ports = templatePorts(template);
  const inputPorts = ports.filter((port) => port.direction === 'in');
  const outputPorts = ports.filter((port) => port.direction === 'out');
  return {
    id,
    atom_id: id,
    atom_type: template.atom_type,
    type: template.atom_type,
    template_id: template.id,
    category: template.category,
    origin: 'builtin',
    operation: template.operation,
    description: template.description,
    ports,
    input_ports: inputPorts,
    output_ports: outputPorts,
    evidence_refs: template.evidence_refs,
    readiness_status: 'not_configured',
    execution_status: 'not_run',
    security_status: 'trusted',
    parameters: {},
    config: {},
    metadata: { template_id: template.id },
    position,
  };
}

export function createEmptyMarkerAtom(spec: EmptyMarkerSpec, index: number) {
  const ports: AtomPortRecord[] = [
    { name: 'marker_in', direction: 'in', schema: spec.input_schema, required: false },
    { name: 'marker_out', direction: 'out', schema: spec.output_schema, required: false },
  ];
  return {
    id: spec.atom_id,
    atom_id: spec.atom_id,
    atom_type: 'empty_marker',
    type: 'empty_marker',
    template_id: spec.template_id,
    category: spec.category,
    origin: 'builtin',
    operation: 'empty_marker',
    description: `${spec.label}; no processing is executed.`,
    ports,
    input_ports: ports.filter((port) => port.direction === 'in'),
    output_ports: ports.filter((port) => port.direction === 'out'),
    evidence_refs: [],
    readiness_status: 'ready',
    execution_status: 'not_run',
    security_status: 'trusted',
    parameters: {},
    config: {
      empty_processing: true,
      state_marker: spec.atom_id,
      no_op: true,
      input_schema: spec.input_schema,
      output_schema: spec.output_schema,
    },
    metadata: {
      empty_atom: true,
      auto_generated_empty_atom: true,
      skipped_processing_category: spec.category,
      input_schema: spec.input_schema,
      output_schema: spec.output_schema,
    },
    position: { x: 680, y: 110 + index * 118 },
  };
}

export function generateAtomId(flow: Record<string, unknown>, template: Pick<AtomTemplate, 'operation' | 'atom_type' | 'id'>) {
  const baseId = template.operation || template.atom_type || template.id;
  const existingIds = new Set(flowAtoms(flow).map((atom) => String(atom.id)));
  let index = existingIds.size + 1;
  let id = `${baseId}_${index}`;
  while (existingIds.has(id)) {
    index += 1;
    id = `${baseId}_${index}`;
  }
  return id;
}

export function addAtomToFlow(flow: Record<string, unknown>, atom: Record<string, unknown>): Record<string, unknown> {
  const atomKey = atomCollectionKey(flow);
  const nextAtoms = [...asRecords(flow[atomKey]), atom];
  return {
    ...flow,
    [atomKey]: nextAtoms,
    ...(atomKey === 'flow_atoms' && Array.isArray(flow.nodes) ? { nodes: nextAtoms } : {}),
  };
}

export function addTemplateAtomToFlow(
  flow: Record<string, unknown>,
  template: AtomTemplate,
  position: { x: number; y: number }
) {
  const id = generateAtomId(flow, template);
  const atom = createFlowAtomFromTemplate(template, id, position);
  return { flow: addAtomToFlow(flow, atom), atom };
}

export function addMissingEmptyMarkerAtoms(
  flow: Record<string, unknown>,
  specs: EmptyMarkerSpec[]
): Record<string, unknown> {
  if (specs.length === 0) return flow;
  let nextFlow = flow;
  const existingIds = new Set(flowAtoms(flow).map((atom) => String(atom.id)));
  specs.forEach((spec, index) => {
    if (!existingIds.has(spec.atom_id)) {
      nextFlow = addAtomToFlow(nextFlow, createEmptyMarkerAtom(spec, index));
      existingIds.add(spec.atom_id);
    }
  });
  return nextFlow;
}

export function addEmptyMarkerForCategory(
  flow: Record<string, unknown>,
  specs: EmptyMarkerSpec[],
  category: string
): Record<string, unknown> {
  const spec = specs.find((item) => item.category === category);
  if (!spec) return flow;
  return addMissingEmptyMarkerAtoms(flow, [spec]);
}

export function removeUnconnectedAutoEmptyMarkerAtoms(flow: Record<string, unknown>): Record<string, unknown> {
  const atomKey = atomCollectionKey(flow);
  const atoms = asRecords(flow[atomKey]);
  const connectedIds = new Set(
    asRecords(flow.edges).flatMap((edge) => [String(edge.source || ''), String(edge.target || '')])
  );
  const nextAtoms = atoms.filter((atom) => {
    const metadata = (atom.metadata as Record<string, unknown>) || {};
    const autoEmpty = metadata.auto_generated_empty_atom === true && (
      atom.operation === 'empty_marker' || atom.atom_type === 'empty_marker' || metadata.empty_atom === true
    );
    return !autoEmpty || connectedIds.has(String(atom.id));
  });

  if (nextAtoms.length === atoms.length) return flow;
  return {
    ...flow,
    [atomKey]: nextAtoms,
    ...(atomKey === 'flow_atoms' && Array.isArray(flow.nodes) ? { nodes: nextAtoms } : {}),
  };
}

export function wouldCreateCycle(edges: Edge[], source: string, target: string): boolean {
  const adjacency = new Map<string, string[]>();
  [...edges, { id: '__next__', source, target } as Edge].forEach((edge) => {
    const current = adjacency.get(edge.source) || [];
    current.push(edge.target);
    adjacency.set(edge.source, current);
  });

  const stack = [target];
  const seen = new Set<string>();
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current || seen.has(current)) continue;
    if (current === source) return true;
    seen.add(current);
    stack.push(...(adjacency.get(current) || []));
  }
  return false;
}

export function connectionProblem(
  connection: Connection,
  atoms: Array<Record<string, unknown>>,
  edges: Edge[],
  policy: OrderPolicy
): string | null {
  if (!connection.source || !connection.target) return 'Choose a source and target atom.';
  if (connection.source === connection.target) return 'Self-links are not allowed.';

  const atomById = new Map(atoms.map((atom) => [String(atom.id), atom]));
  const sourceAtom = atomById.get(connection.source);
  const targetAtom = atomById.get(connection.target);
  const sourcePort = findPort(sourceAtom, connection.sourceHandle, 'out');
  const targetPort = findPort(targetAtom, connection.targetHandle, 'in');
  if (!sourceAtom || !targetAtom) return 'Choose atoms that exist on the canvas.';
  if (!sourcePort) return `${String(sourceAtom.id)} has no output port for this link.`;
  if (!targetPort) return `${String(targetAtom.id)} has no input port for this link.`;

  const targetAlreadyConnected = edges.some(
    (edge) =>
      edge.target === connection.target &&
      String(edge.targetHandle || findPort(targetAtom, edge.targetHandle, 'in')?.name || 'input') === targetPort.name
  );
  if (targetPort.required && targetAlreadyConnected) return `Input '${targetPort.name}' is already connected.`;

  if (sourcePort.schema !== targetPort.schema) {
    return `Schema mismatch: ${sourcePort.schema} cannot feed ${targetPort.schema} without an adapter.`;
  }

  if (wouldCreateCycle(edges, connection.source, connection.target)) return 'Cycle blocked: this link would feed a downstream atom back upstream.';

  const sourceCategory = String(sourceAtom?.category || '');
  const targetCategory = String(targetAtom?.category || '');
  const sourceRank = categoryOrder[sourceCategory];
  const targetRank = categoryOrder[targetCategory];
  if (!policy.allow_order_violations && sourceRank !== undefined && targetRank !== undefined && sourceRank > targetRank) {
    return `Order policy blocked: ${sourceCategory} cannot feed earlier-stage ${targetCategory}.`;
  }

  return null;
}

export function maybeConnectLastCompatible(
  flow: Record<string, unknown>,
  atom: Record<string, unknown>
): Record<string, unknown> {
  const atoms = flowAtoms(flow).filter((item) => String(item.id) !== String(atom.id));
  const targetPort = findPort(atom, undefined, 'in');
  if (!targetPort) return flow;

  const candidates = atoms
    .map((candidate) => ({ atom: candidate, port: findPort(candidate, undefined, 'out') }))
    .filter((candidate) => candidate.port?.schema === targetPort.schema);
  const source = candidates[candidates.length - 1];
  if (!source?.port) return flow;

  const edges = asRecords(flow.edges);
  const targetAlreadyConnected = edges.some(
    (existing) => String(existing.target) === String(atom.id) && edgeTargetHandle(existing) === targetPort.name
  );
  if (targetAlreadyConnected) return flow;
  const edge = {
    id: `edge-${String(source.atom.id)}-${String(atom.id)}-${edges.length + 1}`,
    source: String(source.atom.id),
    target: String(atom.id),
    source_handle: source.port.name,
    target_handle: targetPort.name,
  };
  return { ...flow, edges: [...edges, edge] };
}

export function connectAtomRequiredInputs(
  flow: Record<string, unknown>,
  targetAtom: Record<string, unknown>,
  allowedSourceIds?: Set<string>
): Record<string, unknown> {
  return connectAtomRequiredInputsWithReport(flow, targetAtom, allowedSourceIds).flow;
}

export function connectAtomRequiredInputsWithReport(
  flow: Record<string, unknown>,
  targetAtom: Record<string, unknown>,
  allowedSourceIds?: Set<string>
): ConnectReport {
  const targetId = String(targetAtom.id);
  const atoms = flowAtoms(flow).filter((item) => String(item.id) !== targetId);
  let edges = asRecords(flow.edges);
  const connectedEdges: Array<Record<string, unknown>> = [];
  const skippedInputs: ConnectSkippedInput[] = [];
  const targetPorts = getAtomPorts(targetAtom).filter((port) => port.direction === 'in' && port.required);
  const policy = getOrderPolicy(flow);

  targetPorts.forEach((targetPort) => {
    const alreadyConnected = edges.some(
      (edge) => String(edge.target) === targetId && edgeTargetHandle(edge) === targetPort.name
    );
    if (alreadyConnected) {
      skippedInputs.push({
        target_atom_id: targetId,
        target_input: targetPort.name,
        schema: targetPort.schema,
        reason: 'already_connected',
      });
      return;
    }

    const candidates = atoms
      .map((candidate) => ({
        atom: candidate,
        port: getAtomPorts(candidate).find((port) => port.direction === 'out' && port.schema === targetPort.schema),
      }))
      .filter((candidate) => {
        if (!candidate.port) return false;
        if (allowedSourceIds && !allowedSourceIds.has(String(candidate.atom.id))) return false;
        const sourceCategory = String(candidate.atom.category || '');
        const targetCategory = String(targetAtom.category || '');
        const sourceRank = categoryOrder[sourceCategory];
        const targetRank = categoryOrder[targetCategory];
        if (!policy.allow_order_violations && sourceRank !== undefined && targetRank !== undefined && sourceRank > targetRank) {
          return false;
        }
        const edgeLike = edges.map((edge) => ({
          id: String(edge.id),
          source: String(edge.source),
          target: String(edge.target),
        })) as Edge[];
        return !wouldCreateCycle(edgeLike, String(candidate.atom.id), targetId);
      });
    const source = candidates[candidates.length - 1];
    if (!source?.port) {
      const allOutputAtoms = atoms.filter((atom) => getAtomPorts(atom).some((port) => port.direction === 'out'));
      const schemaMatches = allOutputAtoms.filter((atom) =>
        getAtomPorts(atom).some((port) => port.direction === 'out' && port.schema === targetPort.schema)
      );
      const allowedSchemaMatches = allowedSourceIds
        ? schemaMatches.filter((atom) => allowedSourceIds.has(String(atom.id)))
        : schemaMatches;
      const edgeLike = edges.map((edge) => ({
        id: String(edge.id),
        source: String(edge.source),
        target: String(edge.target),
      })) as Edge[];
      const cycleFreeMatches = allowedSchemaMatches.filter((atom) => !wouldCreateCycle(edgeLike, String(atom.id), targetId));
      const orderAllowedMatches = cycleFreeMatches.filter((atom) => {
        const sourceRank = categoryOrder[String(atom.category || '')];
        const targetRank = categoryOrder[String(targetAtom.category || '')];
        return policy.allow_order_violations || sourceRank === undefined || targetRank === undefined || sourceRank <= targetRank;
      });
      let reason = 'no_schema_match';
      if (allOutputAtoms.length === 0) reason = 'no_upstream_atoms';
      else if (schemaMatches.length === 0) reason = 'schema_mismatch';
      else if (allowedSourceIds && allowedSchemaMatches.length === 0) reason = 'upstream_not_allowed';
      else if (cycleFreeMatches.length === 0) reason = 'would_create_cycle';
      else if (orderAllowedMatches.length === 0) reason = 'order_policy_blocked';
      skippedInputs.push({
        target_atom_id: targetId,
        target_input: targetPort.name,
        schema: targetPort.schema,
        reason,
      });
      return;
    }

    const edge = {
      id: `edge-${String(source.atom.id)}-${targetId}-${edges.length + 1}`,
      source: String(source.atom.id),
      target: targetId,
      source_handle: source.port.name,
      target_handle: targetPort.name,
    };
    edges = [...edges, edge];
    connectedEdges.push(edge);
  });

  return { flow: { ...flow, edges }, connected_edges: connectedEdges, skipped_inputs: skippedInputs };
}

export function connectChecklistAtoms(flow: Record<string, unknown>, checklist: FlowChecklist): Record<string, unknown> {
  return connectChecklistAtomsWithReport(flow, checklist).flow;
}

export function connectChecklistAtomsWithReport(
  flow: Record<string, unknown>,
  checklist: FlowChecklist
): ConnectReport {
  let nextFlow = flow;
  const connectedEdges: Array<Record<string, unknown>> = [];
  const skippedInputs: ConnectSkippedInput[] = [];
  checklist.steps.forEach((step, index) => {
    const atoms = flowAtoms(nextFlow);
    const target = firstChecklistStepAtom(atoms, step);
    if (!target) return;
    const allowedSources = new Set<string>(
      checklist.steps.slice(0, index).flatMap((upstreamStep) => {
        const upstreamAtom = firstChecklistStepAtom(atoms, upstreamStep);
        return upstreamAtom ? [String(upstreamAtom.id)] : [];
      })
    );
    step.depends_on.forEach((slotId) => {
      const upstreamStep = checklist.steps.find((candidate) => candidate.slot_id === slotId);
      const upstreamAtom = upstreamStep ? firstChecklistStepAtom(atoms, upstreamStep) : undefined;
      if (upstreamAtom) allowedSources.add(String(upstreamAtom.id));
    });
    const report = connectAtomRequiredInputsWithReport(
      nextFlow,
      target,
      allowedSources.size > 0 ? allowedSources : undefined
    );
    nextFlow = report.flow;
    connectedEdges.push(...report.connected_edges);
    skippedInputs.push(...report.skipped_inputs);
  });
  return { flow: nextFlow, connected_edges: connectedEdges, skipped_inputs: skippedInputs };
}

function checklistStepSkipped(atoms: Array<Record<string, unknown>>, step: FlowChecklistStep): boolean {
  if (!step.allow_empty_marker) return false;
  return atoms.some((atom) => {
    const metadata = (atom.metadata as Record<string, unknown>) || {};
    return (
      (atom.operation === 'empty_marker' || atom.atom_type === 'empty_marker' || metadata.empty_atom === true) &&
      metadata.skipped_processing_category === step.category
    );
  });
}

export function buildChecklistMissingSequence(
  flow: Record<string, unknown>,
  checklist: FlowChecklist,
  templates: AtomTemplate[],
  choices: Record<string, ChecklistChoice> = {}
): ChecklistBuildPreview {
  let nextFlow = flow;
  const completed = new Set<string>();
  const addedAtoms: ChecklistAddedAtom[] = [];
  const connectedEdges: Array<Record<string, unknown>> = [];
  const skippedInputs: ConnectSkippedInput[] = [];

  checklist.steps.forEach((step, index) => {
    const currentAtoms = flowAtoms(nextFlow);
    const existing = firstChecklistStepAtom(currentAtoms, step);
    const skipped = checklistStepSkipped(currentAtoms, step);
    if (existing || skipped) {
      completed.add(step.slot_id);
      return;
    }
    if (step.depends_on.some((slot) => !completed.has(slot))) return;
    const template = findChecklistStepTemplate(step, templates, choices[step.slot_id]?.template_id);
    if (!template) return;
    const added = addTemplateAtomToFlow(nextFlow, template, {
      x: 120 + (index % 3) * 250,
      y: 90 + Math.floor(index / 3) * 150,
    });
    nextFlow = withChecklistChoice(added.flow, checklist.scenario_id, step.slot_id, {
      template_id: template.id,
      atom_id: String(added.atom.id),
      skipped: false,
    });
    addedAtoms.push({
      slot_id: step.slot_id,
      atom_id: String(added.atom.id),
      template_id: template.id,
      label: step.label,
    });
    const report = connectAtomRequiredInputsWithReport(nextFlow, added.atom);
    nextFlow = report.flow;
    connectedEdges.push(...report.connected_edges);
    skippedInputs.push(...report.skipped_inputs);
    completed.add(step.slot_id);
  });

  return { flow: nextFlow, added_atoms: addedAtoms, connected_edges: connectedEdges, skipped_inputs: skippedInputs };
}

export function previewEmptyRiskRemoval(flow: Record<string, unknown>): EmptyRiskRemovalPreview {
  const atomKey = atomCollectionKey(flow);
  const atoms = asRecords(flow[atomKey]);
  const removedAtoms: EmptyRiskRemovalPreview['removed_atoms'] = [];
  const clearedSlots = new Set<string>();
  const nextAtoms = atoms.filter((atom) => {
    const metadata = (atom.metadata as Record<string, unknown>) || {};
    const empty = atom.operation === 'empty_marker' || atom.atom_type === 'empty_marker' || metadata.empty_atom === true;
    if (!empty) return true;
    removedAtoms.push({
      atom_id: String(atom.id),
      category: String(metadata.skipped_processing_category || atom.category || ''),
      slot_id: metadata.checklist_slot_id ? String(metadata.checklist_slot_id) : undefined,
      skip_reason: metadata.skip_reason ? String(metadata.skip_reason) : undefined,
    });
    if (metadata.checklist_slot_id) clearedSlots.add(String(metadata.checklist_slot_id));
    return false;
  });
  const removedIds = new Set(removedAtoms.map((atom) => atom.atom_id));
  const nextEdges = asRecords(flow.edges).filter(
    (edge) => !removedIds.has(String(edge.source || '')) && !removedIds.has(String(edge.target || ''))
  );
  const metadata = (flow.metadata as Record<string, unknown>) || {};
  const checklist = ((metadata.checklist as Record<string, unknown>) || {}) as Record<string, unknown>;
  const choices = ((checklist.choices as Record<string, ChecklistChoice>) || {}) as Record<string, ChecklistChoice>;
  const nextChoices = Object.fromEntries(
    Object.entries(choices).map(([slotId, choice]) => {
      if (!clearedSlots.has(slotId)) return [slotId, choice];
      const { skipped: _skipped, skip_reason: _skipReason, ...rest } = choice;
      return [slotId, rest];
    })
  );
  const nextFlow = {
    ...flow,
    [atomKey]: nextAtoms,
    ...(atomKey === 'flow_atoms' && Array.isArray(flow.nodes) ? { nodes: nextAtoms } : {}),
    edges: nextEdges,
    metadata: {
      ...metadata,
      order_policy: {
        ...((metadata.order_policy as OrderPolicy) || {}),
        allow_empty_edges: false,
      },
      checklist: {
        ...checklist,
        choices: nextChoices,
        updated_at: new Date().toISOString(),
      },
    },
  };
  return { flow: nextFlow, removed_atoms: removedAtoms, cleared_slots: [...clearedSlots] };
}

export function generateChecklistReport(flow: Record<string, unknown>, checklist: FlowChecklist) {
  const atoms = flowAtoms(flow);
  const choices = getChecklistChoices(flow);
  const completed = new Set<string>();
  const steps = checklist.steps.map((step) => {
    const atom = firstChecklistStepAtom(atoms, step);
    const skipped = checklistStepSkipped(atoms, step) || choices[step.slot_id]?.skipped === true;
    const blocked_by = step.depends_on.filter((slot) => !completed.has(slot));
    const input_statuses = atom ? getAtomInputStatuses(flow, atom) : [];
    const missing_inputs = input_statuses.filter((input) => input.required && !input.connected).map((input) => input.schema);
    let status = step.required ? 'missing' : 'optional';
    if (atom && missing_inputs.length === 0) status = 'complete';
    else if (atom) status = 'needs_link';
    else if (skipped) status = 'skipped';
    else if (blocked_by.length > 0) status = 'blocked';
    if (status === 'complete' || status === 'skipped') completed.add(step.slot_id);
    return {
      slot_id: step.slot_id,
      label: step.label,
      required: step.required,
      status,
      atom_id: atom ? String(atom.id) : choices[step.slot_id]?.atom_id || '',
      template_id: atom ? atomTemplateId(atom) : choices[step.slot_id]?.template_id || '',
      skipped,
      skip_reason: choices[step.slot_id]?.skip_reason || '',
      blocked_by,
      missing_inputs,
      input_statuses,
    };
  });
  const metadata = getChecklistMetadata(flow);
  return {
    generated_at: new Date().toISOString(),
    scenario_id: checklist.scenario_id,
    scenario_label: checklist.label,
    checklist_version: checklist.version,
    recommendation_source: metadata.recommendation_source || '',
    summary: {
      total: steps.length,
      complete: steps.filter((step) => step.status === 'complete').length,
      skipped: steps.filter((step) => step.status === 'skipped').length,
      needs_link: steps.filter((step) => step.status === 'needs_link').length,
      missing: steps.filter((step) => step.status === 'missing' || step.status === 'blocked').length,
    },
    steps,
    edges: asRecords(flow.edges).map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      source_handle: edge.source_handle,
      target_handle: edge.target_handle,
    })),
  };
}
