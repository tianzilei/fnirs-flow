import { useState, useMemo } from 'react';
import { Filter } from 'lucide-react';
import { useStore } from '../store';

export function ValidationDashboard() {
  const result = useStore((s) => s.validation);
  const loading = useStore((s) => s.loading);
  const validate = useStore((s) => s.validate);
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [domainFilter, setDomainFilter] = useState<string>('all');

  const domains = useMemo(() => {
    if (!result) return [];
    const seen = new Set(result.risks.map((r) => String(r.domain)).filter(Boolean));
    return Array.from(seen).sort();
  }, [result]);

  const filteredRisks = useMemo(() => {
    if (!result) return [];
    return result.risks.filter((risk) => {
      const severityMatch = severityFilter === 'all' || String(risk.severity) === severityFilter;
      const domainMatch = domainFilter === 'all' || String(risk.domain) === domainFilter;
      return severityMatch && domainMatch;
    });
  }, [result, severityFilter, domainFilter]);

  return (
    <div className="page validation-dashboard work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Readiness</span>
          <h2>Validation Dashboard</h2>
        </div>
        <div className="page-actions">
          <button className="primary-button" onClick={validate} disabled={loading}>
            {loading ? 'Validating...' : 'Run Validation'}
          </button>
        </div>
      </section>

      {result && (
        <div className="validation-results">
          <div className={`status-badge ${result.is_valid ? 'valid' : 'invalid'}`}>
            {result.is_valid ? 'VALID' : 'INVALID'}
          </div>

          {result.errors.length > 0 && (
            <section className="errors-section">
              <h3>Errors ({result.errors.length})</h3>
              <ul>
                {result.errors.map((err, i) => (
                  <li key={i} className="error-item">{err}</li>
                ))}
              </ul>
            </section>
          )}

          {result.warnings.length > 0 && (
            <section className="warnings-section">
              <h3>Warnings ({result.warnings.length})</h3>
              <ul>
                {result.warnings.map((warn, i) => (
                  <li key={i} className="warning-item">{warn}</li>
                ))}
              </ul>
            </section>
          )}

          {result.risks.length > 0 && (
            <section className="risks-section">
              <div className="risks-header">
                <h3>Risks ({filteredRisks.length}{filteredRisks.length !== result.risks.length ? ` / ${result.risks.length}` : ''})</h3>
                <div className="risk-filters">
                  <Filter size={14} />
                  <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
                    <option value="all">All Severity</option>
                    <option value="fatal">Fatal</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                  {domains.length > 0 && (
                    <select value={domainFilter} onChange={(e) => setDomainFilter(e.target.value)}>
                      <option value="all">All Domains</option>
                      {domains.map((d) => <option key={d} value={d}>{d}</option>)}
                    </select>
                  )}
                </div>
              </div>
              <table className="risks-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Domain</th>
                    <th>Message</th>
                    <th>Suggested Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRisks.map((risk, i) => (
                    <tr key={i} className={`risk-${risk.severity}`}>
                      <td><span className={`severity-badge ${risk.severity}`}>{String(risk.severity)}</span></td>
                      <td>{String(risk.domain)}</td>
                      <td>{String(risk.message)}</td>
                      <td>{String(risk.suggested_action)}</td>
                    </tr>
                  ))}
                  {filteredRisks.length === 0 && (
                    <tr><td colSpan={4} className="muted" style={{ textAlign: 'center', padding: '16px' }}>No risks match the current filters.</td></tr>
                  )}
                </tbody>
              </table>
            </section>
          )}

          {result.errors.length === 0 && result.warnings.length === 0 && filteredRisks.length === 0 && (
            <div className="all-clear">
              {result.risks.length === 0
                ? 'No issues found. The flow is valid and ready for execution.'
                : 'All risks filtered out. Adjust filters to see risk details.'}
            </div>
          )}
        </div>
      )}

      {!result && (
        <div className="empty-state">
          <p>Click "Run Validation" to check the flow configuration.</p>
        </div>
      )}
    </div>
  );
}
