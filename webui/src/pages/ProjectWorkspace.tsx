import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Archive, Boxes, Copy, Database, Play, Download, ShieldCheck } from 'lucide-react';
import { useStore } from '../store';
import type { Project } from '../api/client';
import { VersionHistoryPanel } from '../components/VersionHistoryPanel';
import { DesignHistoryPanel } from '../components/DesignHistoryPanel';

export function ProjectWorkspace() {
  const navigate = useNavigate();
  const projects = useStore((s) => s.projects);
  const project = useStore((s) => s.project);
  const loading = useStore((s) => s.loading);
  const loadProjects = useStore((s) => s.loadProjects);
  const createProject = useStore((s) => s.createProject);
  const selectProject = useStore((s) => s.selectProject);

  const [newName, setNewName] = React.useState('');
  const [newDesc, setNewDesc] = React.useState('');
  const [showCreate, setShowCreate] = React.useState(false);
  const [detailProject, setDetailProject] = React.useState<Project | null>(null);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const handleCreate = async () => {
    if (newName.trim()) {
      try {
        const proj = await createProject(newName.trim(), newDesc.trim());
        setNewName('');
        setNewDesc('');
        setShowCreate(false);
        navigate(`/projects/${proj.id}/flow`);
      } catch {
        // error handled in store
      }
    }
  };

  const handleOpen = (proj: Project) => {
    selectProject(proj);
    navigate(`/projects/${proj.id}/flow`);
  };

  const handleCardClick = (proj: Project) => {
    if (detailProject?.id === proj.id) {
      setDetailProject(null);
    } else {
      setDetailProject(proj);
    }
  };

  const handleRestored = async (restored: Project) => {
    setDetailProject(restored);
    if (project?.id === restored.id) {
      await selectProject(restored);
    }
    await loadProjects();
  };

  return (
    <div className="page project-workspace work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Workspace</span>
          <h2>Projects</h2>
        </div>
        <button
          className="primary-button"
          onClick={() => setShowCreate(!showCreate)}
        >
          {showCreate ? 'Cancel' : '+ New Project'}
        </button>
      </section>

      {showCreate && (
        <div className="create-project">
          <div className="create-project-fields">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Project name (required)"
              autoFocus
              onKeyDown={(e) => e.key === 'Enter' && newName.trim() && handleCreate()}
            />
            <input
              type="text"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="Description (optional)"
              onKeyDown={(e) => e.key === 'Enter' && newName.trim() && handleCreate()}
            />
          </div>
          <button
            className="primary-button"
            onClick={handleCreate}
            disabled={!newName.trim() || loading}
          >
            {loading ? 'Creating...' : 'Create'}
          </button>
        </div>
      )}

      {loading && projects.length === 0 && (
        <div className="loading-state">Loading projects...</div>
      )}

      <div className="project-list">
        {projects.map((proj: Project) => (
          <div key={proj.id} className="project-card-wrapper">
            <div
              role="button"
              tabIndex={0}
              className={`project-card ${project?.id === proj.id ? 'selected' : ''} ${detailProject?.id === proj.id ? 'expanded' : ''}`}
              onClick={() => handleCardClick(proj)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  handleCardClick(proj);
                }
              }}
            >
              <div className="project-card-header">
                <h3>{proj.name}</h3>
                <span className="project-id-badge">{proj.id.slice(0, 8)}</span>
              </div>
              {proj.description && <p className="project-desc">{proj.description}</p>}
                {proj.flow_id && <p className="flow-id">Flow: {proj.flow_id}</p>}
                <p className="project-storage-badge"><Archive size={13} /> Single-file project · r{proj.revision}</p>
            </div>

            {detailProject?.id === proj.id && (
              <div className="project-detail">
                <div className="detail-row">
                  <span className="detail-label">Full ID</span>
                  <span className="detail-value">{proj.id}</span>
                </div>
                {proj.description && (
                  <div className="detail-row">
                    <span className="detail-label">Description</span>
                    <span className="detail-value">{proj.description}</span>
                  </div>
                )}
                {proj.flow_id && (
                  <div className="detail-row">
                    <span className="detail-label">Flow ID</span>
                    <span className="detail-value">{proj.flow_id}</span>
                  </div>
                )}
                <div className="detail-row">
                  <span className="detail-label">Storage</span>
                  <span className="detail-value project-storage-value">
                    <ShieldCheck size={14} /> {proj.integrity_status === 'verified' ? 'Verified' : proj.integrity_status === 'failed' ? 'Integrity failed' : 'Not yet verified'} .fnirsflow bundle · revision {proj.revision}
                  </span>
                </div>
                {proj.integrity_error && (
                  <div className="project-integrity-error" role="alert">{proj.integrity_error}</div>
                )}
                <div className="detail-row project-package-row">
                  <span className="detail-label">Project file</span>
                  <span className="detail-value"><code>{proj.package_path}</code></span>
                  <button
                    className="ghost-button small"
                    onClick={() => navigator.clipboard.writeText(proj.package_path)}
                    title="Copy project package path"
                  >
                    <Copy size={14} />
                  </button>
                </div>
                <button
                  className="primary-button"
                  onClick={() => handleOpen(proj)}
                >
                  Open Project
                </button>
                <div className="quick-entry-buttons">
                  <button className="ghost-button" onClick={() => handleOpen(proj)}>
                    <Boxes size={14} /> Flow
                  </button>
                  <button className="ghost-button" onClick={() => { selectProject(proj); navigate(`/projects/${proj.id}/data`); }}>
                    <Database size={14} /> Data
                  </button>
                  <button className="ghost-button" onClick={() => { selectProject(proj); navigate(`/projects/${proj.id}/runs`); }}>
                    <Play size={14} /> Runs
                  </button>
                  <button className="ghost-button" onClick={() => { selectProject(proj); navigate(`/projects/${proj.id}/package`); }}>
                    <Download size={14} /> Export
                  </button>
                </div>
                <VersionHistoryPanel projectId={proj.id} onRestored={handleRestored} />
                <DesignHistoryPanel projectId={proj.id} />
              </div>
            )}
          </div>
        ))}

        {!loading && projects.length === 0 && (
          <div className="empty-state">
            <p>No projects yet. Click "+ New Project" to create one.</p>
          </div>
        )}
      </div>
    </div>
  );
}
