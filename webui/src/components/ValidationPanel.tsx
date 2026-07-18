import { Sparkles } from 'lucide-react';
import type { ValidationResult } from '../api/client';

interface ValidationPanelProps {
  result: ValidationResult | null;
  onOpenAIDraft?: () => void;
  onRiskSelect?: (risk: Record<string, unknown>) => void;
}

function isChecklistRisk(risk: Record<string, unknown>) {
  return String(risk.code || '').startsWith('CHECKLIST_') ||
    String(risk.affected_object || '').startsWith('checklist:');
}

function RiskItem({
  risk,
  onRiskSelect,
}: {
  risk: Record<string, unknown>;
  onRiskSelect?: (risk: Record<string, unknown>) => void;
}) {
  const clickable = isChecklistRisk(risk) && !!onRiskSelect;
  const content = (
    <>
      <span className="risk-severity">[{String(risk.severity || '')}]</span>
      <span className="risk-message">{String(risk.message || '')}</span>
      {risk.code ? <span className="risk-code">{String(risk.code)}</span> : null}
      {risk.suggested_action ? (
        <span className="risk-action">Action: {String(risk.suggested_action)}</span>
      ) : null}
    </>
  );
  if (!clickable) {
    return <div className={`risk ${String(risk.severity || '')}`}>{content}</div>;
  }
  return (
    <button
      className={`risk risk-button ${String(risk.severity || '')}`}
      onClick={() => onRiskSelect?.(risk)}
      type="button"
    >
      {content}
    </button>
  );
}

export function ValidationPanel({ result, onOpenAIDraft, onRiskSelect }: ValidationPanelProps) {
  if (!result) {
    return (
      <aside className="validation-panel">
        <div className="validation-heading"><h3>Validation</h3>
          {onOpenAIDraft ? <button className="ghost-button compact" onClick={onOpenAIDraft}><Sparkles size={14} />AI Draft</button> : null}
        </div>
        <p className="muted">Click Validate to check the flow.</p>
      </aside>
    );
  }

  return (
    <aside className="validation-panel">
      <div className="validation-heading"><h3>Validation</h3>
        {onOpenAIDraft ? <button className="ghost-button compact" onClick={onOpenAIDraft}><Sparkles size={14} />AI Draft</button> : null}
      </div>
      <div className={`status ${result.is_valid ? 'valid' : 'invalid'}`}>
        {result.is_valid ? 'Valid' : 'Invalid'}
      </div>

      {result.errors.length > 0 && (
        <div className="section">
          <h4>Errors ({result.errors.length})</h4>
          {result.errors.map((e, i) => (
            <div key={i} className="error">{e}</div>
          ))}
        </div>
      )}

      {result.warnings.length > 0 && (
        <div className="section">
          <h4>Warnings ({result.warnings.length})</h4>
          {result.warnings.map((w, i) => (
            <div key={i} className="warning">{w}</div>
          ))}
        </div>
      )}

      {result.risks.length > 0 && (
        <div className="section">
          <h4>Risks ({result.risks.length})</h4>
          {result.risks.map((r, i) => (
            <RiskItem key={i} risk={r} onRiskSelect={onRiskSelect} />
          ))}
        </div>
      )}

      {/* Backend-specific risks */}
      {result.risks.some(r => String(r.domain || '') === 'backend') && (
        <div className="section backend-risks">
          <h4>Backend Risks</h4>
          {result.risks
            .filter(r => String(r.domain || '') === 'backend')
            .map((r, i) => (
              <RiskItem key={i} risk={r} onRiskSelect={onRiskSelect} />
            ))}
        </div>
      )}
    </aside>
  );
}
