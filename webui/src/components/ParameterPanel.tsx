import { useRef, useState } from 'react';
import { ChevronDown, ChevronLeft, Download, FolderOpen, Upload } from 'lucide-react';
import {
  buildParameterDataJson,
  parseParameterData,
  shouldUseBulkParameterIO,
} from '../flow/parameterBulkIO';

interface AtomInfo {
  atom_id?: string;
  atom_type?: string;
  template_id?: string;
  operation?: string;
  evidence_refs?: string[];
  readiness_status?: string;
  backend_id?: string;
  available_backends?: string[];
}

interface Parameter {
  name: string;
  type: string;
  value: unknown;
  control?: string;
  description?: string;
  placeholder?: string;
  advanced?: boolean;
  modified?: boolean;
  source?: string;  // 'template_default' | 'user_override' | 'evidence'
  options?: unknown[];
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  min?: number;
  max?: number;
  range?: [number, number] | { min?: number; max?: number; minimum?: number; maximum?: number };
}

interface NormalizedOption {
  key: string;
  label: string;
  value: unknown;
}

interface ProjectDataFolder {
  name: string;
  path: string;
  has_children: boolean;
}

interface ParameterPanelProps {
  title: string;
  parameters: Parameter[];
  onChange: (name: string, value: unknown) => void;
  onBulkChange?: (values: Record<string, unknown>) => void;
  defaultCollapsed?: boolean;
  warnings?: string[];
  atomInfo?: AtomInfo;
  loadProjectFolders?: (parent: string) => Promise<ProjectDataFolder[]>;
}

type ParameterKind = 'boolean' | 'number' | 'number-list' | 'text';

function isPathParameter(param: Parameter): boolean {
  if (param.control) return param.control === 'path';
  if (typeof param.value !== 'string') return false;
  return /(^|_)(path|file|dir|folder|directory|csv|tsv|snirf|bids_dir|reference_dir)$/i.test(param.name);
}

function normalizeRelativePathInput(value: string): string | null {
  const raw = value.trim();
  if (!raw) return '';
  if (/^(?:[A-Za-z]:[\\/]|\/|\\\\|~|[a-z][a-z0-9+.-]*:\/\/)/i.test(raw)) return null;
  const normalized = raw.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  const parts = normalized.split('/');
  if (parts.some((part) => !part || part === '.' || part === '..' || part.includes(':'))) return null;
  return parts.join('/');
}

function parentFolder(path: string): string {
  const parts = path.split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
}

function applyFolderSelection(currentValue: unknown, folderPath: string): string {
  const current = String(currentValue ?? '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  const fileName = current.split('/').pop() || '';
  if (fileName.includes('.') && folderPath) return `${folderPath}/${fileName}`;
  if (fileName.includes('.') && !folderPath) return fileName;
  return folderPath;
}

function valueKind(value: unknown): ParameterKind {
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return 'number';
  if (Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === 'number')) {
    return 'number-list';
  }
  return 'text';
}

function parameterKind(param: Parameter): ParameterKind {
  if (param.type === 'boolean' || param.type === 'number' || param.type === 'number-list') return param.type;
  return valueKind(param.value);
}

function normalizeOptionItem(item: unknown, index: number): NormalizedOption {
  if (item && typeof item === 'object' && !Array.isArray(item)) {
    const record = item as Record<string, unknown>;
    if ('value' in record) {
      const value = record.value;
      return {
        key: `${index}:${JSON.stringify(value)}`,
        label: String(record.label ?? value ?? ''),
        value,
      };
    }
  }
  return {
    key: `${index}:${JSON.stringify(item)}`,
    label: String(item ?? ''),
    value: item,
  };
}

function optionValues(param: Parameter): NormalizedOption[] {
  const explicit = param.options || param.enum;
  if (explicit && explicit.length > 0) return explicit.map(normalizeOptionItem);
  if (typeof param.value === 'string' && param.value.includes('|')) {
    return param.value
      .split('|')
      .map((item) => item.trim())
      .filter(Boolean)
      .map(normalizeOptionItem);
  }
  return [];
}

function optionMatchesValue(option: NormalizedOption, value: unknown): boolean {
  return option.value === value || String(option.value ?? '') === String(value ?? '');
}

function selectedOptionKey(options: NormalizedOption[], value: unknown): string {
  return options.find((option) => optionMatchesValue(option, value))?.key || '';
}

function numberRange(param: Parameter): string {
  const range = param.range;
  const min =
    Array.isArray(range) ? range[0] :
    typeof range === 'object' && range ? range.minimum ?? range.min :
    param.minimum ?? param.min;
  const max =
    Array.isArray(range) ? range[1] :
    typeof range === 'object' && range ? range.maximum ?? range.max :
    param.maximum ?? param.max;
  if (min !== undefined && max !== undefined) return `${min} to ${max}`;
  if (min !== undefined) return `>= ${min}`;
  if (max !== undefined) return `<= ${max}`;
  return '';
}

function formatEditableValue(value: unknown): string {
  if (Array.isArray(value) || (value && typeof value === 'object')) return JSON.stringify(value);
  return String(value ?? '');
}

function parseEditableValue(previousValue: unknown, nextValue: string): unknown {
  if (Array.isArray(previousValue) || (previousValue && typeof previousValue === 'object')) {
    try {
      return JSON.parse(nextValue);
    } catch {
      return nextValue;
    }
  }
  return nextValue;
}

export function ParameterPanel({
  title,
  parameters,
  onChange,
  onBulkChange,
  defaultCollapsed = true,
  warnings = [],
  atomInfo,
  loadProjectFolders,
}: ParameterPanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [basicCollapsed, setBasicCollapsed] = useState(false);
  const [advancedCollapsed, setAdvancedCollapsed] = useState(defaultCollapsed);
  const [pathError, setPathError] = useState<Record<string, string>>({});
  const [folderParam, setFolderParam] = useState<string | null>(null);
  const [folderParent, setFolderParent] = useState('');
  const [folderEntries, setFolderEntries] = useState<ProjectDataFolder[]>([]);
  const [folderLoading, setFolderLoading] = useState(false);
  const [bulkStatus, setBulkStatus] = useState('');
  const bulkFileInputRef = useRef<HTMLInputElement | null>(null);

  const basicParams = parameters.filter((p) => !p.advanced);
  const advancedParams = parameters.filter((p) => p.advanced);
  const modifiedCount = parameters.filter((p) => p.modified).length;
  const bulkMode = shouldUseBulkParameterIO(parameters);

  const exportTemplate = () => {
    const json = buildParameterDataJson(parameters, atomInfo);
    const blob = new Blob([json], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const atomId = atomInfo?.atom_id || atomInfo?.operation || title;
    link.href = url;
    link.download = `${atomId.replace(/[^A-Za-z0-9_.-]+/g, '_')}_parameters.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setBulkStatus(`Exported a JSON template containing ${parameters.length} parameters.`);
  };

  const importData = async (file: File | null | undefined) => {
    if (!file) return;
    try {
      const text = await file.text();
      const result = parseParameterData(text, file.name, parameters);
      const entries = Object.entries(result.values);
      if (entries.length === 0) {
        setBulkStatus('The imported file contains no matching parameters.');
        return;
      }
      if (onBulkChange) {
        onBulkChange(result.values);
      } else {
        entries.forEach(([name, value]) => onChange(name, value));
      }
      const ignoredSuffix = result.ignored.length > 0 ? ` Ignored ${result.ignored.length} unknown parameters.` : '';
      setBulkStatus(`Imported ${entries.length} parameter values.${ignoredSuffix}`);
    } catch (error) {
      setBulkStatus(error instanceof Error ? error.message : 'Import failed.');
    }
  };

  const renderParam = (param: Parameter) => {
    const kind = parameterKind(param);
    const options = optionValues(param);
    const currentValue = String(param.value ?? '');
    const canSelect = kind !== 'boolean' && kind !== 'number-list' && options.length > 0;
    const selectedKey = selectedOptionKey(options, param.value);
    const pathParam = isPathParameter(param);

    const updatePathParam = (value: string) => {
      const cleanValue = normalizeRelativePathInput(value);
      if (cleanValue === null) {
        setPathError((current) => ({ ...current, [param.name]: 'Use a project-relative path, not an absolute path.' }));
        return;
      }
      setPathError((current) => {
        const next = { ...current };
        delete next[param.name];
        return next;
      });
      onChange(param.name, cleanValue);
    };

    const openFolderPicker = async () => {
      if (!loadProjectFolders) return;
      setFolderParam(param.name);
      const parent = parentFolder(String(param.value ?? '').replace(/\\/g, '/'));
      setFolderParent(parent);
      setFolderLoading(true);
      try {
        setFolderEntries(await loadProjectFolders(parent));
      } finally {
        setFolderLoading(false);
      }
    };

    const browseTo = async (path: string) => {
      if (!loadProjectFolders) return;
      setFolderParent(path);
      setFolderLoading(true);
      try {
        setFolderEntries(await loadProjectFolders(path));
      } finally {
        setFolderLoading(false);
      }
    };

    return (
      <div key={param.name} className={`param-row ${param.modified ? 'modified' : ''}`}>
        <label className="param-label">
          {param.name}
          {param.modified && <span className="modified-badge">modified</span>}
          {param.source && <span className="param-source" title={`Source: ${param.source}`}>source: {param.source}</span>}
        </label>
        <div className="param-control">
          <div className="param-input">
            {kind === 'boolean' ? (
              <input
                type="checkbox"
                checked={param.value === true}
                onChange={(e) => onChange(param.name, e.target.checked)}
              />
            ) : canSelect ? (
              <select
                value={selectedKey}
                onChange={(e) => {
                  const option = options.find((item) => item.key === e.target.value);
                  if (option) onChange(param.name, option.value);
                }}
              >
                <option value="" disabled>{currentValue ? `Current: ${currentValue}` : 'Select...'}</option>
                {options.map((opt) => (
                  <option key={opt.key} value={opt.key}>{opt.label}</option>
                ))}
              </select>
            ) : kind === 'number' ? (
              <input
                type="number"
                value={typeof param.value === 'number' ? param.value : ''}
                onChange={(e) => {
                  const val = parseFloat(e.target.value);
                  onChange(param.name, Number.isNaN(val) ? 0 : val);
                }}
              />
            ) : (
              <div className={pathParam ? 'path-input-row' : undefined}>
                <input
                  type="text"
                  value={formatEditableValue(param.value)}
                  onChange={(e) => {
                    if (pathParam) updatePathParam(e.target.value);
                    else onChange(param.name, parseEditableValue(param.value, e.target.value));
                  }}
                  placeholder={param.placeholder || (pathParam ? 'relative/path/inside-project' : undefined)}
                />
                {pathParam && loadProjectFolders && (
                  <button type="button" className="icon-button" onClick={openFolderPicker} title="Browse project folders">
                    <FolderOpen size={14} />
                  </button>
                )}
              </div>
            )}
          </div>
          {pathParam && !param.description && <span className="param-desc">Project-relative path only. Absolute paths are not allowed.</span>}
          {pathError[param.name] && <span className="param-error">{pathError[param.name]}</span>}
          {pathParam && folderParam === param.name && loadProjectFolders && (
            <div className="param-folder-picker">
              <div className="folder-browser-header">
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => browseTo(parentFolder(folderParent))}
                  disabled={!folderParent || folderLoading}
                  title="Up one folder"
                >
                  <ChevronLeft size={14} />
                </button>
                <code>{folderParent || '/'}</code>
                <button type="button" className="ghost-button compact" onClick={() => setFolderParam(null)}>
                  Close
                </button>
              </div>
              {folderLoading && <span className="param-desc">Loading folders...</span>}
              {!folderLoading && folderEntries.length === 0 && <span className="param-desc">No child folders.</span>}
              <div className="folder-list compact-list">
                {folderEntries.map((folder) => (
                  <button
                    key={folder.path}
                    type="button"
                    className="folder-list-item"
                    onClick={() => browseTo(folder.path)}
                  >
                    <FolderOpen size={13} />
                    <span>{folder.name}</span>
                    <small>{folder.path}</small>
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="secondary-button compact"
                onClick={() => {
                  onChange(param.name, applyFolderSelection(param.value, folderParent));
                  setFolderParam(null);
                }}
              >
                Use this folder
              </button>
            </div>
          )}
          {(kind === 'number' || kind === 'number-list') && numberRange(param) && (
            <span className="param-range">Range: {numberRange(param)}</span>
          )}
          {param.description && <span className="param-desc">{param.description}</span>}
        </div>
      </div>
    );
  };

  const renderGroup = (
    label: string,
    items: Parameter[],
    isCollapsed: boolean,
    setIsCollapsed: (collapsed: boolean) => void
  ) => {
    if (items.length === 0) return null;
    return (
      <section className="param-group">
        <button
          type="button"
          className="param-group-header"
          onClick={() => setIsCollapsed(!isCollapsed)}
          aria-expanded={!isCollapsed}
        >
          <ChevronDown className={`collapse-icon ${isCollapsed ? 'collapsed' : 'expanded'}`} size={14} />
          <h4>{label}</h4>
          <span>{items.length}</span>
        </button>
        {!isCollapsed && <div className="param-group-body">{items.map(renderParam)}</div>}
      </section>
    );
  };

  const renderBulkParameterIO = () => (
    <section className="bulk-param-panel">
      <div className="bulk-param-summary">
        <strong>{parameters.length} parameters</strong>
        <span>Export a JSON template, fill in the parameters externally, then import the completed template.</span>
      </div>
      <div className="bulk-param-actions">
        <button type="button" className="icon-text-button" onClick={exportTemplate}>
          <Download size={14} />
          <span>Export Template</span>
        </button>
        <button type="button" className="icon-text-button subtle" onClick={() => bulkFileInputRef.current?.click()}>
          <Upload size={14} />
          <span>Import Data</span>
        </button>
        <input
          ref={bulkFileInputRef}
          type="file"
          accept=".json,application/json"
          className="hidden-file-input"
          onChange={(event) => {
            void importData(event.currentTarget.files?.[0]);
            event.currentTarget.value = '';
          }}
        />
      </div>
      {modifiedCount > 0 && <span className="bulk-param-note">{modifiedCount} parameters imported or edited manually.</span>}
      {bulkStatus && <span className="bulk-param-note">{bulkStatus}</span>}
    </section>
  );

  return (
    <div className="parameter-panel">
      <div className="panel-header">
        <button
          type="button"
          className="panel-title-button"
          onClick={() => setCollapsed(!collapsed)}
          aria-expanded={!collapsed}
        >
          <ChevronDown className={`collapse-icon ${collapsed ? 'collapsed' : 'expanded'}`} size={15} />
          <h3>{title}</h3>
          {modifiedCount > 0 && <span className="modified-count">{modifiedCount} modified</span>}
        </button>
      </div>

      {atomInfo && !collapsed && (
        <div className="atom-info-bar">
          {atomInfo.atom_type && <span className="atom-type">{atomInfo.atom_type}</span>}
          {atomInfo.operation && atomInfo.operation !== atomInfo.atom_type && (
            <span className="atom-operation">{atomInfo.operation}</span>
          )}
          {atomInfo.template_id && (
            <span className="atom-template" title="Source template">template: {atomInfo.template_id}</span>
          )}
          {atomInfo.readiness_status && (
            <span className={`atom-readiness ${atomInfo.readiness_status}`}>
              {atomInfo.readiness_status}
            </span>
          )}
          {atomInfo.evidence_refs && atomInfo.evidence_refs.length > 0 && (
            <span className="atom-evidence" title={atomInfo.evidence_refs.join(', ')}>
              evidence: {atomInfo.evidence_refs.length}
            </span>
          )}
          {atomInfo.available_backends && atomInfo.available_backends.length > 0 && (
            <span className="atom-backend">
              backend: {atomInfo.backend_id || 'default'}
            </span>
          )}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="panel-warnings">
          {warnings.map((w, i) => (
            <div key={i} className="warning-badge">{w}</div>
          ))}
        </div>
      )}

      {collapsed && modifiedCount > 0 && (
        <div className="modified-summary">
          {parameters
            .filter((p) => p.modified)
            .map((p) => (
              <span key={p.name} className="modified-param">
                {p.name}: {String(p.value)}
              </span>
            ))}
        </div>
      )}

      {!collapsed && (
        <div className="panel-content">
          {bulkMode ? (
            renderBulkParameterIO()
          ) : (
            <>
              {renderGroup('Basic Parameters', basicParams, basicCollapsed, setBasicCollapsed)}
              {renderGroup('Advanced Parameters', advancedParams, advancedCollapsed, setAdvancedCollapsed)}
            </>
          )}
        </div>
      )}
    </div>
  );
}
