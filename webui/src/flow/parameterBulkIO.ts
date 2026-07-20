export interface BulkParameter {
  name: string;
  type: string;
  value: unknown;
  description?: string;
}

export interface BulkAtomInfo {
  atom_id?: string;
  atom_type?: string;
  template_id?: string;
  operation?: string;
}

export interface ImportedParameterData {
  values: Record<string, unknown>;
  ignored: string[];
}

export const TEXT_PARAMETER_BULK_THRESHOLD = 3;
export const BULK_PARAMETER_FORMAT = 'fnirs-flow.atom-parameters.v1';

const CSV_COLUMNS = ['atom_id', 'atom_type', 'operation', 'parameter', 'type', 'value', 'description'];

function csvCell(value: unknown): string {
  const text = value === undefined || value === null ? '' : String(value);
  if (!/[",\r\n]/.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

function editableValue(value: unknown): string {
  if (Array.isArray(value) || (value && typeof value === 'object')) return JSON.stringify(value);
  return value === undefined || value === null ? '' : String(value);
}

function parameterType(param: BulkParameter): string {
  if (param.type) return param.type;
  if (Array.isArray(param.value)) return 'array';
  if (param.value === null) return 'null';
  return typeof param.value;
}

export function shouldUseBulkParameterIO(parameters: BulkParameter[]): boolean {
  return parameters.filter(isTextParameter).length > TEXT_PARAMETER_BULK_THRESHOLD;
}

function isTextParameter(param: BulkParameter): boolean {
  if (param.type === 'boolean' || param.type === 'number' || param.type === 'number-list') return false;
  if (typeof param.value === 'boolean' || typeof param.value === 'number') return false;
  if (Array.isArray(param.value) && param.value.every((item) => typeof item === 'number')) return false;
  return true;
}

export function buildParameterTemplateCsv(parameters: BulkParameter[], atomInfo?: BulkAtomInfo): string {
  const rows = [
    CSV_COLUMNS,
    ...parameters.map((param) => [
      atomInfo?.atom_id || '',
      atomInfo?.atom_type || '',
      atomInfo?.operation || atomInfo?.template_id || '',
      param.name,
      parameterType(param),
      editableValue(param.value),
      param.description || '',
    ]),
  ];
  return `${rows.map((row) => row.map(csvCell).join(',')).join('\n')}\n`;
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];

    if (quoted) {
      if (char === '"' && next === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
      continue;
    }

    if (char === '"') {
      quoted = true;
    } else if (char === ',') {
      row.push(cell);
      cell = '';
    } else if (char === '\n') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else if (char !== '\r') {
      cell += char;
    }
  }

  if (cell || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((candidate) => candidate.some((item) => item.trim()));
}

function parseWithPreviousType(previous: BulkParameter | undefined, rawValue: unknown): unknown {
  if (typeof rawValue !== 'string') return rawValue;
  const value = rawValue.trim();
  const previousValue = previous?.value;

  if (Array.isArray(previousValue) || (previousValue && typeof previousValue === 'object')) {
    try {
      return JSON.parse(value || (Array.isArray(previousValue) ? '[]' : '{}'));
    } catch {
      return rawValue;
    }
  }

  if (typeof previousValue === 'boolean' || previous?.type === 'boolean') {
    if (/^(true|1|yes|y)$/i.test(value)) return true;
    if (/^(false|0|no|n)$/i.test(value)) return false;
    return Boolean(value);
  }

  if (typeof previousValue === 'number' || previous?.type === 'number') {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : previousValue ?? 0;
  }

  if (value === 'null') return null;
  if (/^-?\d+(\.\d+)?$/.test(value)) return Number(value);
  if (/^(true|false)$/i.test(value)) return value.toLowerCase() === 'true';
  return rawValue;
}

function parseJsonParameters(text: string): Record<string, unknown> | null {
  const parsed = JSON.parse(text) as unknown;
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const record = parsed as Record<string, unknown>;
    if (record.parameters && typeof record.parameters === 'object' && !Array.isArray(record.parameters)) {
      return extractJsonParameterValues(record.parameters as Record<string, unknown>);
    }
    return extractJsonParameterValues(record);
  }
  return null;
}

function extractJsonParameterValues(data: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(data).map(([name, value]) => {
    if (
      value &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      Object.prototype.hasOwnProperty.call(value, 'value') &&
      (Object.prototype.hasOwnProperty.call(value, 'type') || Object.prototype.hasOwnProperty.call(value, 'description'))
    ) {
      return [name, (value as { value: unknown }).value];
    }
    return [name, value];
  }));
}

export function parseParameterData(
  text: string,
  fileName: string,
  parameters: BulkParameter[],
): ImportedParameterData {
  const existing = new Map(parameters.map((param) => [param.name, param]));
  const values: Record<string, unknown> = {};
  const ignored: string[] = [];
  const trimmed = text.trim();

  if (!trimmed) return { values, ignored };

  if (fileName.toLowerCase().endsWith('.json') || trimmed.startsWith('{')) {
    const data = parseJsonParameters(trimmed);
    if (!data) return { values, ignored };
    Object.entries(data).forEach(([name, value]) => {
      const previous = existing.get(name);
      if (!previous) {
        ignored.push(name);
        return;
      }
      values[name] = parseWithPreviousType(previous, value);
    });
    return { values, ignored };
  }

  const rows = parseCsv(trimmed);
  const [header, ...body] = rows;
  const normalizedHeader = header.map((name) => name.trim().toLowerCase());
  const nameIndex = normalizedHeader.indexOf('parameter');
  const valueIndex = normalizedHeader.indexOf('value');
  if (nameIndex === -1 || valueIndex === -1) return { values, ignored };

  body.forEach((row) => {
    const name = row[nameIndex]?.trim();
    if (!name) return;
    const previous = existing.get(name);
    if (!previous) {
      ignored.push(name);
      return;
    }
    values[name] = parseWithPreviousType(previous, row[valueIndex] ?? '');
  });

  return { values, ignored };
}

export function buildParameterDataJson(parameters: BulkParameter[], atomInfo?: BulkAtomInfo): string {
  return JSON.stringify(
    {
      format: BULK_PARAMETER_FORMAT,
      atom: {
        id: atomInfo?.atom_id || '',
        type: atomInfo?.atom_type || '',
        operation: atomInfo?.operation || '',
        template_id: atomInfo?.template_id || '',
      },
      parameters: Object.fromEntries(parameters.map((param) => [
        param.name,
        {
          value: param.value,
          type: parameterType(param),
          description: param.description || '',
        },
      ])),
    },
    null,
    2,
  );
}
