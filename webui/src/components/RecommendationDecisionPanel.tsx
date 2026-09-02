import { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Info } from 'lucide-react';
import { confirmProjectRecommendation, getProjectRecommendation, type RecommendationDecision } from '../api/client';

type Props = { projectId: string };

/** Read-only, explicit rendering of the backend decision contract. */
export function RecommendationDecisionPanel({ projectId }: Props) {
  const [decision, setDecision] = useState<RecommendationDecision | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'missing' | 'error'>('loading');
  const [reviewer, setReviewer] = useState('');
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    let active = true;
    setState('loading');
    getProjectRecommendation(projectId)
      .then((value) => { if (active) { setDecision(value); setState('ready'); } })
      .catch((error: { response?: { status?: number } }) => {
        if (active) setState(error.response?.status === 404 ? 'missing' : 'error');
      });
    return () => { active = false; };
  }, [projectId]);

  if (state === 'loading' || state === 'missing') return null;
  if (state === 'error') {
    return <section className="workflow-panel recommendation-panel" role="status"><p>Recommendation status unavailable.</p></section>;
  }
  if (!decision) return null;
  const needsReview = decision.decision_status === 'needs_review';
  const reasons = decision.reasons || [];
  const evidenceCount = Array.isArray(decision.syntheses) ? decision.syntheses.length : 0;
  const handleConfirm = async () => {
    if (!reviewer.trim()) return;
    const result = await confirmProjectRecommendation(projectId, decision.decision_id, reviewer);
    setDecision(result.decision);
    setConfirmed(true);
  };
  return (
    <section className="workflow-panel recommendation-panel" aria-label="Recommendation decision">
      <div className="section-heading compact">
        <div><span className="page-kicker">Backend decision</span><h3>Recommendation status</h3></div>
        {needsReview ? <AlertCircle size={18} aria-label="Needs review" /> : <CheckCircle2 size={18} aria-label="Eligible" />}
      </div>
      <div className="recommendation-status-grid">
        <span>Status <strong>{decision.decision_status}</strong></span>
        <span>Tier <strong>{decision.tier || '—'}</strong></span>
        <span>Execution <strong>{decision.execution_status}</strong></span>
        <span>Mode <strong>{decision.source_mode}</strong></span>
      </div>
      {reasons.length > 0 && <ul className="recommendation-reasons">{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
      <p className="recommendation-evidence-note"><Info size={14} /> {evidenceCount} evidence synthesis record(s); user confirmation is required before adoption.</p>
      {needsReview ? <button type="button" className="ghost-button compact" disabled>Review required</button> : (
        <div className="recommendation-confirmation">
          <input aria-label="Reviewer name" placeholder="Reviewer name" value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
          <button type="button" className="ghost-button compact" onClick={handleConfirm} disabled={!reviewer.trim() || confirmed}>{confirmed ? 'Confirmed' : 'Confirm selection'}</button>
        </div>
      )}
    </section>
  );
}
