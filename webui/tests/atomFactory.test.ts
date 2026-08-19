import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildChecklistMissingSequence,
  checklistTemplateRecommendations,
  clearChecklistChoiceForAtom,
  connectChecklistAtomsWithReport,
  connectAtomRequiredInputsWithReport,
  connectSkipReasonText,
  createFlowAtomFromTemplate,
  generateChecklistReport,
  getAtomInputStatuses,
  inferChecklistScenario,
  atomMatchesChecklistStep,
  previewEmptyRiskRemoval,
  withChecklistChoice,
} from '../src/flow/atomFactory.ts';

const checklist = {
  scenario_id: 'task_glm',
  label: 'Task GLM',
  description: '',
  version: 'test',
  steps: [
    {
      slot_id: 'data_input',
      label: 'Data input',
      required: true,
      recommended_template_ids: ['dataset_discovery'],
      recommended_atom_types: ['dataset_discovery'],
      default_template_id: 'dataset_discovery',
      alternative_template_ids: [],
      input_requirements: [],
      depends_on: [],
      allow_empty_marker: false,
      category: 'data',
      guidance: '',
    },
    {
      slot_id: 'read_run',
      label: 'Read run',
      required: true,
      recommended_template_ids: ['read_run'],
      recommended_atom_types: ['read_run'],
      default_template_id: 'read_run',
      alternative_template_ids: [],
      input_requirements: ['DataManifest'],
      depends_on: ['data_input'],
      allow_empty_marker: false,
      category: 'data',
      guidance: '',
    },
    {
      slot_id: 'quality_control',
      label: 'Quality control',
      required: false,
      recommended_template_ids: ['qc_metrics'],
      recommended_atom_types: ['signal_qc'],
      default_template_id: 'qc_metrics',
      alternative_template_ids: [],
      input_requirements: ['RawData'],
      depends_on: ['read_run'],
      allow_empty_marker: true,
      category: 'validation',
      guidance: '',
    },
  ],
};

function flowWithLinearAtoms() {
  return {
    flow_id: 'f1',
    flow_atoms: [
      {
        id: 'dataset',
        template_id: 'dataset_discovery',
        atom_type: 'dataset_discovery',
        operation: 'dataset_discovery',
        category: 'data',
        ports: [{ name: 'manifest', direction: 'out', schema: 'DataManifest', required: true }],
      },
      {
        id: 'reader',
        template_id: 'read_run',
        atom_type: 'read_run',
        operation: 'read_run',
        category: 'data',
        ports: [
          { name: 'manifest', direction: 'in', schema: 'DataManifest', required: true },
          { name: 'raw', direction: 'out', schema: 'RawData', required: true },
        ],
      },
      {
        id: 'qc',
        template_id: 'qc_metrics',
        atom_type: 'signal_qc',
        operation: 'qc_metrics',
        category: 'validation',
        ports: [
          { name: 'raw', direction: 'in', schema: 'RawData', required: true },
          { name: 'report', direction: 'out', schema: 'QCReport', required: true },
        ],
      },
    ],
    edges: [],
    metadata: {},
  };
}

test('inferChecklistScenario picks the most specific scenario from atoms', () => {
  assert.equal(inferChecklistScenario({ flow_atoms: [{ template_id: 'svm_model', category: 'analysis' }] }), 'ml_classification');
  assert.equal(
    inferChecklistScenario({ flow_atoms: [{ template_id: 'connectivity_analysis', category: 'analysis' }] }),
    'resting_state_connectivity'
  );
  assert.equal(
    inferChecklistScenario({ flow_atoms: [{ template_id: 'participant_table_input', category: 'data' }] }),
    'group_analysis'
  );
  assert.equal(inferChecklistScenario({ flow_atoms: [] }), 'task_glm');
});

test('connectChecklistAtomsWithReport connects compatible required inputs and reports them', () => {
  const report = connectChecklistAtomsWithReport(flowWithLinearAtoms(), checklist);

  assert.equal(report.connected_edges.length, 2);
  assert.deepEqual(
    report.connected_edges.map((edge) => [edge.source, edge.target, edge.target_handle]),
    [
      ['dataset', 'reader', 'manifest'],
      ['reader', 'qc', 'raw'],
    ]
  );
  assert.equal(report.skipped_inputs.filter((item) => item.reason !== 'already_connected').length, 0);

  const qc = report.flow.flow_atoms.find((node) => node.id === 'qc');
  assert.deepEqual(getAtomInputStatuses(report.flow, qc).map((input) => input.connected), [true]);
});

test('buildChecklistMissingSequence previews added atoms and links without mutating the original', () => {
  const templates = [
    {
      id: 'dataset_discovery',
      atom_type: 'dataset_discovery',
      display_name: 'Dataset discovery',
      category: 'data',
      operation: 'dataset_discovery',
      description: '',
      input_ports: [],
      output_ports: [{ name: 'manifest', schema: 'DataManifest', required: true }],
      evidence_refs: [],
    },
    {
      id: 'read_run',
      atom_type: 'read_run',
      display_name: 'Read run',
      category: 'data',
      operation: 'read_run',
      description: '',
      input_ports: [{ name: 'manifest', schema: 'DataManifest', required: true }],
      output_ports: [{ name: 'raw', schema: 'RawData', required: true }],
      evidence_refs: [],
    },
    {
      id: 'qc_metrics',
      atom_type: 'signal_qc',
      display_name: 'QC',
      category: 'validation',
      operation: 'qc_metrics',
      description: '',
      input_ports: [{ name: 'raw', schema: 'RawData', required: true }],
      output_ports: [{ name: 'report', schema: 'QCReport', required: true }],
      evidence_refs: [],
    },
  ];

  const preview = buildChecklistMissingSequence({ flow_atoms: [], edges: [], metadata: {} }, checklist, templates);

  assert.deepEqual(preview.added_atoms.map((atom) => atom.template_id), ['dataset_discovery', 'read_run', 'qc_metrics']);
  assert.equal(preview.connected_edges.length, 2);
  assert.equal((preview.flow.flow_atoms as Array<Record<string, unknown>>).length, 3);
});

test('connectAtomRequiredInputsWithReport reports detailed failure reasons', () => {
  const target = {
    id: 'target',
    category: 'analysis',
    ports: [{ name: 'features', direction: 'in', schema: 'FeatureMatrix', required: true }],
  };

  const noUpstream = connectAtomRequiredInputsWithReport({ flow_atoms: [target], edges: [] }, target);
  assert.equal(noUpstream.skipped_inputs[0].reason, 'no_upstream_atoms');

  const mismatch = connectAtomRequiredInputsWithReport({
    flow_atoms: [
      target,
      { id: 'source', category: 'data', ports: [{ name: 'raw', direction: 'out', schema: 'RawData', required: true }] },
    ],
    edges: [],
  }, target);
  assert.equal(mismatch.skipped_inputs[0].reason, 'schema_mismatch');
});

test('previewEmptyRiskRemoval removes empty atoms and clears skip choices', () => {
  const flow = {
    flow_atoms: [
      {
        id: 'empty_preprocessing',
        atom_type: 'empty_marker',
        operation: 'empty_marker',
        category: 'preprocessing',
        metadata: {
          empty_atom: true,
          skipped_processing_category: 'preprocessing',
          checklist_slot_id: 'filtering',
          skip_reason: 'method_not_needed',
        },
      },
    ],
    edges: [{ id: 'e1', source: 'empty_preprocessing', target: 'target' }],
    metadata: {
      order_policy: { allow_empty_edges: true },
      checklist: {
        scenario_id: 'task_glm',
        choices: { filtering: { skipped: true, skip_reason: 'method_not_needed', template_id: 'bandpass_filter' } },
      },
    },
  };

  const preview = previewEmptyRiskRemoval(flow);

  assert.equal(preview.removed_atoms[0].atom_id, 'empty_preprocessing');
  assert.deepEqual(preview.cleared_slots, ['filtering']);
  assert.equal(preview.flow.metadata.order_policy.allow_empty_edges, false);
  assert.equal(preview.flow.metadata.checklist.choices.filtering.skipped, undefined);
  assert.equal(preview.flow.metadata.checklist.choices.filtering.template_id, 'bandpass_filter');
  assert.equal((preview.flow.edges as unknown[]).length, 0);
});

test('generateChecklistReport summarizes checklist state', () => {
  const connected = connectChecklistAtomsWithReport(flowWithLinearAtoms(), checklist).flow;
  const report = generateChecklistReport(connected, checklist);

  assert.equal(report.scenario_id, 'task_glm');
  assert.equal(report.summary.complete, 3);
  assert.equal(report.steps[1].status, 'complete');
  assert.equal(report.steps[2].input_statuses[0].connected, true);
});

test('withChecklistChoice preserves previous metadata and records slot choices', () => {
  const flow = {
    metadata: {
      checklist: {
        scenario_id: 'task_glm',
        recommendation_source: 'user',
        choices: {
          old_slot: { template_id: 'old_template' },
        },
      },
    },
  };

  const nextFlow = withChecklistChoice(flow, 'task_glm', 'quality_control', {
    template_id: 'sci_check',
    skipped: true,
    skip_reason: 'method_not_needed',
  });

  assert.equal(nextFlow.metadata.checklist.recommendation_source, 'user');
  assert.equal(nextFlow.metadata.checklist.choices.old_slot.template_id, 'old_template');
  assert.equal(nextFlow.metadata.checklist.choices.quality_control.template_id, 'sci_check');
  assert.equal(nextFlow.metadata.checklist.choices.quality_control.skipped, true);
  assert.equal(nextFlow.metadata.checklist.choices.quality_control.skip_reason, 'method_not_needed');
  assert.ok(nextFlow.metadata.checklist.choices.quality_control.updated_at);
});

test('checklist recommendations tier default, recommended, and alternative templates', () => {
  const step = {
    ...checklist.steps[2],
    default_template_id: 'qc_metrics',
    recommended_template_ids: ['qc_metrics', 'sci_check'],
    alternative_template_ids: ['manual_qc'],
  };

  assert.deepEqual(checklistTemplateRecommendations(step), [
    { template_id: 'qc_metrics', tier: 'best' },
    { template_id: 'sci_check', tier: 'recommended' },
    { template_id: 'manual_qc', tier: 'alternative' },
  ]);
  assert.equal(connectSkipReasonText('order_policy_blocked'), 'Blocked by order policy');
});

test('atom matching accepts legacy operation aliases used by demo flows', () => {
  const studyDesignStep = {
    slot_id: 'study_design',
    label: 'Study design',
    required: true,
    recommended_template_ids: ['study_design'],
    recommended_atom_types: ['study_design'],
    default_template_id: 'study_design',
    alternative_template_ids: [],
    input_requirements: [],
    depends_on: [],
    allow_empty_marker: false,
    category: 'design',
    guidance: '',
  };
  const contrastStep = {
    slot_id: 'contrast',
    label: 'Contrast',
    required: true,
    recommended_template_ids: ['contrast'],
    recommended_atom_types: ['contrast'],
    default_template_id: 'contrast',
    alternative_template_ids: [],
    input_requirements: [],
    depends_on: [],
    allow_empty_marker: false,
    category: 'analysis',
    guidance: '',
  };

  assert.equal(atomMatchesChecklistStep({ operation: 'build_design_matrix' }, studyDesignStep), true);
  assert.equal(atomMatchesChecklistStep({ operation: 'estimate_contrast' }, contrastStep), true);
});

test('createFlowAtomFromTemplate keeps internal defaults out of config', () => {
  const atom = createFlowAtomFromTemplate({
    id: 'group_design_matrix',
    atom_type: 'group_design_matrix',
    display_name: 'Group design',
    category: 'design',
    operation: 'group_design_matrix',
    description: '',
    default_config: {
      design_type: 'two_sample_t',
      readiness_status: 'needs_attention',
      execution_scope: 'group',
      source_atom_id: 'ATOM_group_design_matrix',
    },
    default_readiness_status: 'needs_attention',
    default_execution_scope: 'group',
    input_ports: [],
    output_ports: [],
    evidence_refs: [],
  }, 'group-design-1', { x: 0, y: 0 });

  assert.deepEqual(atom.config, { design_type: 'two_sample_t' });
  assert.equal(atom.readiness_status, 'needs_attention');
  assert.equal(atom.execution_scope, 'group');
});

test('clearChecklistChoiceForAtom removes stale atom and skip markers after canvas deletion', () => {
  const flow = {
    flow_atoms: [{
      id: 'empty_preprocessing',
      atom_type: 'empty_marker',
      operation: 'empty_marker',
      metadata: { checklist_slot_id: 'quality_control', empty_atom: true },
    }],
    metadata: {
      checklist: {
        scenario_id: 'task_glm',
        choices: {
          quality_control: {
            template_id: 'qc_metrics',
            atom_id: 'empty_preprocessing',
            skipped: true,
            skip_reason: 'method_not_needed',
          },
        },
      },
    },
  };

  const nextFlow = clearChecklistChoiceForAtom(flow, flow.flow_atoms[0]);

  assert.equal(nextFlow.metadata.checklist.choices.quality_control.template_id, 'qc_metrics');
  assert.equal(nextFlow.metadata.checklist.choices.quality_control.atom_id, undefined);
  assert.equal(nextFlow.metadata.checklist.choices.quality_control.skipped, undefined);
  assert.equal(nextFlow.metadata.checklist.choices.quality_control.skip_reason, undefined);
});
