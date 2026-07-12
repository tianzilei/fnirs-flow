import { useState } from 'react';

interface AtomInfo {
  atom_id?: string;
  atom_type?: string;
  template_id?: string;
  operation?: string;
  evidence_refs?: string[];
  readiness_status?: string;
}

interface Parameter {
  name: string;
  type: string;
  value: unknown;
  description?: string;
  advanced?: boolean;
  modified?: boolean;
  source?: string;  // 'template_default' | 'user_override' | 'evidence'
  options?: string[];
}

interface ParameterPanelProps {
  title: string;
  parameters: Parameter[];
  onChange: (name: string, value: unknown) => void;
  defaultCollapsed?: boolean;
  warnings?: string[];
  atomInfo?: AtomInfo;
}

export function ParameterPanel({
  title,
  parameters,
  onChange,
  defaultCollapsed = true,
  warnings = [],
  atomInfo,
}: ParameterPanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [expandAll, setExpandAll] = useState(false);

  const basicParams = parameters.filter((p) => !p.advanced);
  const advancedParams = parameters.filter((p) => p.advanced);
  const modifiedCount = parameters.filter((p) => p.modified).length;

  const renderParam = (param: Parameter) => (
    <div key={param.name} className={`param-row ${param.modified ? 'modified' : ''}`}>
      <label className="param-label">
        {param.name}
        {param.modified && <span className="modified-badge">modified</span>}
        {param.source && <span className="param-source" title={`Source: ${param.source}`}>source: {param.source}</span>}
      </label>
      <div className="param-input">
        {param.type === 'boolean' ? (
          <input
            type="checkbox"
            checked={param.value as boolean}
            onChange={(e) => onChange(param.name, e.target.checked)}
          />
        ) : param.type === 'number' ? (
          <input
            type="number"
            value={param.value as number}
            onChange={(e) => {
              const val = parseFloat(e.target.value);
              onChange(param.name, isNaN(val) ? 0 : val);
            }}
          />
        ) : param.type === 'select' ? (
          <select
            value={param.value as string}
            onChange={(e) => onChange(param.name, e.target.value)}
          >
            {(param.options || []).map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            value={String(param.value ?? '')}
            onChange={(e) => onChange(param.name, e.target.value)}
          />
        )}
      </div>
      {param.description && <span className="param-desc">{param.description}</span>}
    </div>
  );

  return (
    <div className="parameter-panel">
      <div
        className="panel-header"
        role="button"
        tabIndex={0}
        onClick={() => setCollapsed(!collapsed)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setCollapsed(!collapsed);
          }
        }}
      >
        <div className="panel-title">
          <span className={`collapse-icon ${collapsed ? 'collapsed' : 'expanded'}`}>▼</span>
          <h3>{title}</h3>
          {modifiedCount > 0 && <span className="modified-count">{modifiedCount} modified</span>}
        </div>
        {!collapsed && (
          <button
            className="expand-all-btn"
            onClick={(e) => {
              e.stopPropagation();
              setExpandAll(!expandAll);
            }}
          >
            {expandAll ? 'Collapse All' : 'Expand All'}
          </button>
        )}
      </div>

      {/* Atom-level info bar (MethodAtom-first) */}
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
        </div>
      )}

      {/* Show warnings even when collapsed */}
      {warnings.length > 0 && (
        <div className="panel-warnings">
          {warnings.map((w, i) => (
            <div key={i} className="warning-badge">{w}</div>
          ))}
        </div>
      )}

      {/* Show modified parameters summary when collapsed */}
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
          <div className="basic-params">
            {basicParams.map(renderParam)}
          </div>

          {advancedParams.length > 0 && (
            <div className="advanced-params">
              <div className="advanced-header">
                <h4>Advanced Parameters</h4>
              </div>
              {(expandAll || !defaultCollapsed) && advancedParams.map(renderParam)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
