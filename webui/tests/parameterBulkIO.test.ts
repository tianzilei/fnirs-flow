import test from 'node:test';
import assert from 'node:assert/strict';
import {
  TEXT_PARAMETER_BULK_THRESHOLD,
  buildParameterDataJson,
  buildParameterTemplateCsv,
  parseParameterData,
  shouldUseBulkParameterIO,
} from '../src/flow/parameterBulkIO.ts';

const parameters = [
  { name: 'enabled', type: 'boolean', value: false },
  { name: 'alpha', type: 'number', value: 0.05 },
  { name: 'channels', type: 'number-list', value: [1, 2] },
  { name: 'metadata', type: 'text', value: { group: 'control' } },
  { name: 'label', type: 'text', value: 'baseline' },
];

test('shouldUseBulkParameterIO turns on when more than three parameters are text-like', () => {
  assert.equal(shouldUseBulkParameterIO(parameters), false);
  assert.equal(
    shouldUseBulkParameterIO([
      { name: 'description', type: 'text', value: '' },
      { name: 'formula', type: 'text', value: '' },
      { name: 'columns', type: 'text', value: ['age', 'sex'] },
      { name: 'metadata', type: 'text', value: { group: 'control' } },
    ]),
    true,
  );
  assert.equal(
    shouldUseBulkParameterIO(Array.from({ length: TEXT_PARAMETER_BULK_THRESHOLD }, (_, index) => ({
      name: `param_${index}`,
      type: 'text',
      value: '',
    }))),
    false,
  );
});

test('shouldUseBulkParameterIO ignores numeric and boolean parameters for template mode', () => {
  assert.equal(
    shouldUseBulkParameterIO([
      { name: 'description', type: 'text', value: '' },
      { name: 'formula', type: 'text', value: '' },
      { name: 'alpha', type: 'number', value: 0.05 },
      { name: 'enabled', type: 'boolean', value: true },
      { name: 'channels', type: 'number-list', value: [1, 2] },
    ]),
    false,
  );
});

test('buildParameterTemplateCsv exports atom context and editable values', () => {
  const csv = buildParameterTemplateCsv(parameters, {
    atom_id: 'atom-1',
    atom_type: 'analysis',
    operation: 'glm',
  });

  assert.match(csv, /^atom_id,atom_type,operation,parameter,type,value,description/);
  assert.match(csv, /atom-1,analysis,glm,enabled,boolean,false,/);
  assert.match(csv, /atom-1,analysis,glm,channels,number-list,"\[1,2\]",/);
});

test('buildParameterDataJson exports all parameters with readable details', () => {
  const template = JSON.parse(buildParameterDataJson(parameters, {
    atom_id: 'atom-1',
    atom_type: 'analysis',
    operation: 'glm',
    template_id: 'ATOM_glm',
  }));

  assert.equal(template.format, 'fnirs-flow.atom-parameters.v1');
  assert.deepEqual(Object.keys(template.parameters), ['enabled', 'alpha', 'channels', 'metadata', 'label']);
  assert.deepEqual(template.parameters.metadata.value, { group: 'control' });
  assert.equal(template.parameters.channels.type, 'number-list');
  assert.equal(template.parameters.label.description, '');
});

test('parseParameterData imports CSV values using existing parameter types', () => {
  const csv = [
    'parameter,value',
    'enabled,true',
    'alpha,0.01',
    'channels,"[3,4,5]"',
    'metadata,"{""group"":""task""}"',
    'unknown,value',
  ].join('\n');

  const imported = parseParameterData(csv, 'params.csv', parameters);

  assert.deepEqual(imported.values, {
    enabled: true,
    alpha: 0.01,
    channels: [3, 4, 5],
    metadata: { group: 'task' },
  });
  assert.deepEqual(imported.ignored, ['unknown']);
});

test('parseParameterData imports JSON parameter payloads', () => {
  const imported = parseParameterData(
    JSON.stringify({ parameters: { enabled: true, alpha: 0.1, label: 'updated' } }),
    'params.json',
    parameters,
  );

  assert.deepEqual(imported.values, {
    enabled: true,
    alpha: 0.1,
    label: 'updated',
  });
});

test('parseParameterData imports generated JSON template entries', () => {
  const imported = parseParameterData(
    JSON.stringify({
      parameters: {
        enabled: { value: true, type: 'boolean', description: '' },
        metadata: { value: { group: 'updated' }, type: 'text', description: 'Participant groups' },
        label: { value: 'template-filled', type: 'text', description: '' },
      },
    }),
    'params.json',
    parameters,
  );

  assert.deepEqual(imported.values, {
    enabled: true,
    metadata: { group: 'updated' },
    label: 'template-filled',
  });
});
