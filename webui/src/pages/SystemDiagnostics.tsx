import { useState, useEffect } from 'react';
import { CheckCircle2, XCircle, Wifi, WifiOff, Server, Info } from 'lucide-react';
import * as api from '../api/client';

export function SystemDiagnostics() {
  const [health, setHealth] = useState<api.HealthStatus | null>(null);
  const [backends, setBackends] = useState<api.BackendDescription[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.getHealth().catch((e) => { setError(e.message || 'Backend unavailable'); return null; }),
      api.getBackends().catch(() => null),
    ])
      .then(([healthData, backendsData]) => {
        setHealth(healthData);
        setBackends(backendsData);
      })
      .finally(() => setLoading(false));
  }, []);

  const isHealthy = health?.status === 'ok' || health?.status === 'healthy';

  return (
    <div className="page system-diagnostics work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">System</span>
          <h2>Diagnostics</h2>
        </div>
      </section>

      <section className="diagnostics-grid">
        <div className={`diagnostic-card ${isHealthy ? 'healthy' : 'unhealthy'}`}>
          <div className="diagnostic-icon">
            {isHealthy ? <CheckCircle2 size={24} /> : <XCircle size={24} />}
          </div>
          <div className="diagnostic-body">
            <h3>Backend API</h3>
            <span className="diagnostic-status">
              {loading ? 'Checking...' : isHealthy ? 'Connected' : 'Unavailable'}
            </span>
            {health?.version && <span className="diagnostic-detail">Version: {health.version}</span>}
            {error && <span className="diagnostic-error">{error}</span>}
          </div>
        </div>

        <div className="diagnostic-card">
          <div className="diagnostic-icon">
            {health ? <Wifi size={24} /> : <WifiOff size={24} />}
          </div>
          <div className="diagnostic-body">
            <h3>Connection</h3>
            <span className="diagnostic-status">
              {health ? 'SSE endpoint reachable' : 'No connection'}
            </span>
            <span className="diagnostic-detail">API Base: /api</span>
          </div>
        </div>

        <div className="diagnostic-card">
          <div className="diagnostic-icon">
            <Server size={24} />
          </div>
          <div className="diagnostic-body">
            <h3>Frontend</h3>
            <span className="diagnostic-status">Running</span>
            <span className="diagnostic-detail">Vite + React + TypeScript</span>
          </div>
        </div>

        <div className="diagnostic-card">
          <div className="diagnostic-icon">
            <Info size={24} />
          </div>
          <div className="diagnostic-body">
            <h3>Environment</h3>
            <span className="diagnostic-status">fnirs-flow WebUI</span>
            <span className="diagnostic-detail">
              React Flow + Axios + Lucide Icons
            </span>
          </div>
        </div>
      </section>

      {backends && (
        <section className="backends-section">
          <h3>Execution Backends</h3>
          <div className="diagnostics-grid">
            {backends.map((info) => (
              <div key={info.backend_id} className={`diagnostic-card ${info.is_available ? 'healthy' : 'unhealthy'}`}>
                <div className="diagnostic-icon">
                  {info.is_available ? <CheckCircle2 size={24} /> : <XCircle size={24} />}
                </div>
                <div className="diagnostic-body">
                  <h3>{info.display_name || info.backend_id}</h3>
                  <span className="diagnostic-status">
                    {info.is_available ? 'Available' : 'Not Available'}
                  </span>
                  {info.description && <span className="diagnostic-detail">{info.description}</span>}
                  {info.dependency_profile_id && (
                    <span className="diagnostic-detail">Profile: {info.dependency_profile_id}</span>
                  )}
                  <span className="diagnostic-detail">Loaded: {info.is_loaded ? 'Yes' : 'No'}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {health && (
        <section className="health-raw">
          <h3>Health Response</h3>
          <pre>{JSON.stringify(health, null, 2)}</pre>
        </section>
      )}
    </div>
  );
}
