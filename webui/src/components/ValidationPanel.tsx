import type { ValidationResult } from '../api/client';

interface ValidationPanelProps {
  result: ValidationResult | null;
}

export function ValidationPanel({ result }: ValidationPanelProps) {
  if (!result) {
    return (
      <aside className="validation-panel">
        <h3>Validation</h3>
        <p className="muted">Click Validate to check the flow.</p>
      </aside>
    );
  }

  return (
    <aside className="validation-panel">
      <h3>Validation</h3>
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
            <div key={i} className={`risk ${String(r.severity || '')}`}>
              <span className="risk-severity">[{String(r.severity || '')}]</span>
              <span className="risk-message">{String(r.message || '')}</span>
              {r.code ? <span className="risk-code">{String(r.code)}</span> : null}
            </div>
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
              <div key={i} className={`risk ${String(r.severity || '')}`}>
                <span className="risk-severity">[{String(r.severity || '')}]</span>
                <span className="risk-message">{String(r.message || '')}</span>
                {r.suggested_action ? (
                  <span className="risk-action">Action: {String(r.suggested_action)}</span>
                ) : null}
              </div>
            ))}
        </div>
      )}
    </aside>
  );
}
