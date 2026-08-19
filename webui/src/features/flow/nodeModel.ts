import type { AtomTemplate } from '../../api/client';
import { editableConfig, getAtomPorts } from '../../flow/atomFactory.ts';

export interface NodeDetail {
  id: string;
  template_id: string;
  atom_type: string;
  operation: string;
  category: string;
  readiness_status: string;
  config: Record<string, unknown>;
  parameters: Record<string, unknown>;
  parameter_options: Record<string, unknown[]>;
  parameter_specs: Record<string, Record<string, unknown>>;
  ports: Array<{ name: string; direction: string; schema: string }>;
}

function atomToDetail(atom: Record<string, unknown>): NodeDetail {
  const metadata = (atom.metadata as Record<string, unknown>) || {};
  return {
    id: String(atom.id),
    template_id: String(atom.template_id || metadata.template_id || ''),
    atom_type: String(atom.atom_type || ''),
    operation: String(atom.operation || ''),
    category: String(atom.category || ''),
    readiness_status: String(atom.readiness_status || atom.status || ''),
    config: (atom.config as Record<string, unknown>) || {},
    parameters: (atom.parameters as Record<string, unknown>) || {},
    parameter_options: {
      ...((metadata.parameter_options as Record<string, unknown[]> | undefined) || {}),
      ...((atom.parameter_options as Record<string, unknown[]> | undefined) || {}),
    },
    parameter_specs: {
      ...((metadata.parameter_specs as Record<string, Record<string, unknown>> | undefined) || {}),
      ...((atom.parameter_specs as Record<string, Record<string, unknown>> | undefined) || {}),
    },
    ports: getAtomPorts(atom).map(({ name, direction, schema }) => ({ name, direction, schema })),
  };
}

function templateMatches(template: AtomTemplate, node: NodeDetail): boolean {
  return Boolean(
    (node.template_id && template.id === node.template_id) ||
    (node.operation && template.operation === node.operation) ||
    (node.atom_type && template.atom_type === node.atom_type),
  );
}

function defaultConfig(atom: Record<string, unknown>, templates: AtomTemplate[]): Record<string, unknown> {
  const metadata = (atom.metadata as Record<string, unknown> | undefined) || {};
  const preferredIds = [String(atom.template_id || ''), String(metadata.template_id || '')].filter(Boolean);
  const byId = templates.find((item) => preferredIds.includes(item.id));
  if (byId) return byId.default_config || {};
  const operation = String(atom.operation || '');
  const byOperation = operation && templates.find((item) => item.operation === operation || item.id === operation);
  if (byOperation) return byOperation.default_config || {};
  const atomType = String(atom.atom_type || '');
  const matches = atomType ? templates.filter((item) => item.atom_type === atomType || item.id === atomType) : [];
  return matches.length === 1 ? matches[0].default_config || {} : {};
}

export function atomToDetailWithDefaults(atom: Record<string, unknown>, templates: AtomTemplate[]): NodeDetail {
  const detail = atomToDetail(atom);
  return { ...detail, config: editableConfig({ ...defaultConfig(atom, templates), ...detail.config }) };
}

export function visibleParameterEntries(node: NodeDetail): Array<[string, unknown]> {
  const entries = Object.entries(editableConfig({ ...node.config, ...node.parameters }));
  return node.operation === 'bids_import' ? entries.filter(([name]) => name !== 'datatype') : entries;
}

export function parameterSpecForNode(
  name: string,
  node: NodeDetail,
  templates: AtomTemplate[],
): Record<string, unknown> {
  const templateSpec = templates.find((template) => templateMatches(template, node))?.parameter_specs?.[name] || {};
  return { ...templateSpec, ...(node.parameter_specs[name] || {}) };
}

export function parameterOptionsForNode(
  name: string,
  value: unknown,
  node: NodeDetail,
  templates: AtomTemplate[],
): unknown[] | undefined {
  if (typeof value !== 'string' && typeof value !== 'number') return undefined;
  const templateOptions = templates.find((template) => templateMatches(template, node))?.parameter_options?.[name] || [];
  const seen = new Set<string>();
  const options = [...(node.parameter_options[name] || []), ...templateOptions].filter((option) => {
    if (typeof option !== 'string' && typeof option !== 'number') return false;
    const key = `${typeof option}:${String(option)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  if (!options.length) return undefined;
  const withCurrent = options.some((option) => String(option) === String(value)) || String(value) === ''
    ? options : [value, ...options];
  return withCurrent.length > 1 ? withCurrent : undefined;
}

export function parameterTypeForValue(value: unknown): string {
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return 'number';
  if (Array.isArray(value) && value.every((item) => typeof item === 'number')) return 'number-list';
  return 'text';
}
