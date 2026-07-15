import { useState, useMemo } from 'react';
import { AlertTriangle, Filter, GitBranch, Wrench } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useStore } from '../store';

type IssueKind = 'connection' | 'configuration' | 'ai' | 'schema' | 'other';

interface ValidationIssue {
  id: string;
  kind: IssueKind;
  severity: string;
  domain: string;
  message: string;
  action: string;
  nodeId: string;
}

function extractNodeId(message: string): string {
  return message.match(/Atom '([^']+)'/)?.[1] || message.match(/atom:([^'"\s]+)/)?.[1] || '';
}

function classifyIssue(message: string, severity = '', domain = ''): IssueKind {
  const text = `${message} ${severity} ${domain}`.toLowerCase();
  if (text.includes('not connected') || text.includes('source_handle') || text.includes('target_handle')) return 'connection';
  if (text.includes('not_configured') || text.includes('configure atom')) return 'configuration';
  if (text.includes('ai') || text.includes('confirmation')) return 'ai';
  if (text.includes('schema') || text.includes('parsing')) return 'schema';
  return 'other';
}

function kindLabel(kind: IssueKind): string {
  return {
    connection: 'Connections',
    configuration: 'Configuration',
    ai: 'AI Review',
    schema: 'Schema',
    other: 'Other',
  }[kind];
}

export function ValidationDashboard() {
  const result = useStore((s) => s.validation);
  const loading = useStore((s) => s.loading);
  const validate = useStore((s) => s.validate);
  const navigate = useNavigate();
  const { id: projectId } = useParams();
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [domainFilter, setDomainFilter] = useState<string>('all');

  const issues = useMemo<ValidationIssue[]>(() => {
    if (!result) return [];
    const warnings = result.warnings.map((message, index) => ({
      id: `warning-${index}`,
      kind: classifyIssue(message),
      severity: 'warning',
      domain: 'graph',
      message,
      action: 'Open the affected node and connect the missing required input.',
      nodeId: extractNodeId(message),
    }));
    const errors = result.errors.map((message, index) => ({
      id: `error-${index}`,
      kind: classifyIssue(message, 'error'),
      severity: 'error',
      domain: 'schema',
      message,
      action: 'Fix the Flow structure and validate again.',
      nodeId: extractNodeId(message),
    }));
    const risks = result.risks.map((risk, index) => {
      const message = String(risk.message || '');
      return {
        id: `risk-${index}`,
        kind: classifyIssue(message, String(risk.severity), String(risk.domain)),
        severity: String(risk.severity || 'risk'),
        domain: String(risk.domain || 'risk'),
        message,
        action: String(risk.suggested_action || 'Review this item and validate again.'),
        nodeId: extractNodeId(message) || extractNodeId(String(risk.affected_object || '')),
      };
    });
    return [...errors, ...warnings, ...risks];
  }, [result]);

  const domains = useMemo(() => {
    const seen = new Set(issues.map((issue) => issue.domain).filter(Boolean));
    return Array.from(seen).sort();
  }, [issues]);

  const filteredIssues = useMemo(() => {
    return issues.filter((issue) => {
      const severityMatch = severityFilter === 'all' || issue.severity === severityFilter;
      const domainMatch = domainFilter === 'all' || issue.domain === domainFilter;
      return severityMatch && domainMatch;
    });
  }, [domainFilter, issues, severityFilter]);

  const groupedIssues = useMemo(() => {
    return filteredIssues.reduce<Record<IssueKind, ValidationIssue[]>>((acc, issue) => {
      (acc[issue.kind] = acc[issue.kind] || []).push(issue);
      return acc;
    }, {} as Record<IssueKind, ValidationIssue[]>);
  }, [filteredIssues]);

  const openNode = (nodeId: string) => {
    if (!projectId || !nodeId) return;
    navigate(`/projects/${projectId}/flow?node=${encodeURIComponent(nodeId)}`);
  };

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
          <section className={`validation-hero ${result.is_valid ? 'valid' : 'invalid'}`}>
            {result.is_valid ? <GitBranch size={22} /> : <AlertTriangle size={22} />}
            <div>
              <span className={`status-badge ${result.is_valid ? 'valid' : 'invalid'}`}>
                {result.is_valid ? 'VALID' : 'INVALID'}
              </span>
              <h3>{result.is_valid ? 'Flow is ready to compile' : `${issues.length} issue${issues.length === 1 ? '' : 's'} need attention`}</h3>
              <p>
                {result.is_valid
                  ? 'No blocking validation issues were found.'
                  : 'Use the grouped fixes below to jump directly to affected nodes.'}
              </p>
            </div>
          </section>

          {issues.length > 0 && (
            <section className="risks-section">
              <div className="risks-header">
                <h3>Fix Queue ({filteredIssues.length}{filteredIssues.length !== issues.length ? ` / ${issues.length}` : ''})</h3>
                <div className="risk-filters">
                  <Filter size={14} />
                  <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
                    <option value="all">All Severity</option>
                    <option value="error">Error</option>
                    <option value="warning">Warning</option>
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
              {(['connection', 'configuration', 'ai', 'schema', 'other'] as IssueKind[]).map((kind) => {
                const group = groupedIssues[kind] || [];
                if (group.length === 0) return null;
                return (
                  <div className="validation-issue-group" key={kind}>
                    <div className="validation-issue-group-title">
                      <Wrench size={15} />
                      <strong>{kindLabel(kind)}</strong>
                      <span>{group.length}</span>
                    </div>
                    {group.map((issue) => (
                      <article className={`validation-fix-card risk-${issue.severity}`} key={issue.id}>
                        <div>
                          <span className={`severity-badge ${issue.severity}`}>{issue.severity}</span>
                          {issue.nodeId && <code>{issue.nodeId}</code>}
                        </div>
                        <p>{issue.message}</p>
                        <small>{issue.action}</small>
                        {issue.nodeId && (
                          <button className="ghost-button compact" onClick={() => openNode(issue.nodeId)}>
                            Open node
                          </button>
                        )}
                      </article>
                    ))}
                  </div>
                );
              })}
              {filteredIssues.length === 0 && (
                <div className="empty-state compact">
                  <p>No issues match the current filters.</p>
                </div>
              )}
            </section>
          )}

          {issues.length === 0 && (
            <div className="all-clear">
              No issues found. The flow is valid and ready for execution.
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
