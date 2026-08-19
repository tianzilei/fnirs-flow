import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Archive, Boxes, ChevronLeft, Copy, Database, Download, FolderOpen, Play, ShieldCheck } from 'lucide-react';
import { useStore } from '../store';
import { selectProject as selectActiveProject, selectProjects } from '../features/project/store';
import { formatApiError, listLocalFolders, type LocalFolder, type Project } from '../api/client';
import { VersionHistoryPanel } from '../components/VersionHistoryPanel';
import { DesignHistoryPanel } from '../components/DesignHistoryPanel';

type FolderSelectionStatus = {
  tone: 'empty' | 'resolved' | 'unavailable';
  label: string;
  message: string;
};

export function ProjectWorkspace() {
  const navigate = useNavigate();
  const projects = useStore(selectProjects);
  const project = useStore(selectActiveProject);
  const loading = useStore((s) => s.loading);
  const loadProjects = useStore((s) => s.loadProjects);
  const createProject = useStore((s) => s.createProject);
  const selectProject = useStore((s) => s.selectProject);

  const [newName, setNewName] = React.useState('');
  const [newDesc, setNewDesc] = React.useState('');
  const [newDataRoot, setNewDataRoot] = React.useState('');
  const [folderStatus, setFolderStatus] = React.useState<FolderSelectionStatus | null>(null);
  const [folderPickerOpen, setFolderPickerOpen] = React.useState(false);
  const [localFolderCurrent, setLocalFolderCurrent] = React.useState('');
  const [localFolderParent, setLocalFolderParent] = React.useState('');
  const [localFolders, setLocalFolders] = React.useState<LocalFolder[]>([]);
  const [localFolderLoading, setLocalFolderLoading] = React.useState(false);
  const [localFolderError, setLocalFolderError] = React.useState('');
  const [showCreate, setShowCreate] = React.useState(false);
  const [detailProject, setDetailProject] = React.useState<Project | null>(null);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const handleCreate = async () => {
    if (newName.trim()) {
      try {
        const proj = await createProject(newName.trim(), newDesc.trim(), newDataRoot.trim());
        setNewName('');
        setNewDesc('');
        setNewDataRoot('');
        setFolderStatus(null);
        setFolderPickerOpen(false);
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

  const folderReady = folderStatus?.tone === 'resolved' && !!newDataRoot.trim();
  const folderBlocked = folderStatus?.tone === 'unavailable';
  const nameReady = newName.trim().length > 0;

  const browseLocalFolder = async (path = '') => {
    setLocalFolderLoading(true);
    setLocalFolderError('');
    try {
      const result = await listLocalFolders(path);
      setLocalFolderCurrent(result.current);
      setLocalFolderParent(result.parent);
      setLocalFolders(result.folders);
    } catch (err) {
      setLocalFolderError(formatApiError(err));
      setLocalFolders([]);
    } finally {
      setLocalFolderLoading(false);
    }
  };

  const openFolderPicker = async () => {
    setFolderPickerOpen(true);
    await browseLocalFolder(newDataRoot || '');
  };

  const useSelectedFolder = () => {
    if (!localFolderCurrent) return;
    setNewDataRoot(localFolderCurrent);
    setFolderStatus({
      tone: 'resolved',
      label: 'Data folder ready',
      message: 'The selected local folder is available to the server.',
    });
    setFolderPickerOpen(false);
  };

  const handleTypedDataRoot = (value: string) => {
    setNewDataRoot(value);
    setFolderStatus(
      value.trim()
        ? {
            tone: 'resolved',
            label: 'Data folder ready',
            message: 'The typed local path will be validated by the server when the project is created.',
          }
        : null
    );
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
            <section className={`create-step-card ${nameReady ? 'complete' : 'active'}`}>
              <div className="create-step-index">1</div>
              <div className="create-step-body">
                <div className="create-step-heading">
                  <h3>Project Name</h3>
                  <span>{nameReady ? 'Ready' : 'Required'}</span>
                </div>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Project name"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && nameReady && folderReady && handleCreate()}
                />
              </div>
            </section>

            <section className={`create-step-card ${folderReady ? 'complete' : nameReady ? 'active' : 'disabled'}`}>
              <div className="create-step-index">2</div>
              <div className="create-step-body">
                <div className="create-step-heading">
                  <h3>Data Path</h3>
                  <span>{folderReady ? 'Available' : folderBlocked ? 'Unavailable' : 'Required'}</span>
                </div>
                <div className={`folder-select-card ${folderStatus?.tone || 'empty'}`}>
                  <div className="folder-select-main">
                    <span className="folder-select-label">
                      {folderStatus?.label || 'Project data folder'}
                    </span>
                    <code>{folderReady ? newDataRoot : 'No usable folder selected'}</code>
                    <span className="folder-select-message">
                      {folderStatus?.message || (nameReady ? 'Choose a local data folder for this project.' : 'Enter a project name first, then choose the data folder.')}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="ghost-button compact"
                    onClick={openFolderPicker}
                    disabled={!nameReady}
                    title={nameReady ? 'Choose a local data folder' : 'Enter a project name first'}
                  >
                    <FolderOpen size={14} /> {folderReady ? 'Change' : 'Choose'}
                  </button>
                </div>
                <label className="create-path-input">
                  <span>Data folder path</span>
                  <input
                    type="text"
                    value={newDataRoot}
                    onChange={(e) => handleTypedDataRoot(e.target.value)}
                    placeholder="E:/path/to/local/dataset"
                    disabled={!nameReady}
                    onKeyDown={(e) => e.key === 'Enter' && nameReady && folderReady && handleCreate()}
                  />
                </label>
                <p className="folder-upload-note">
                  You can browse server-visible folders or type a local path directly. No data is uploaded; processing runs on the server.
                </p>
                {folderPickerOpen && (
                  <div className="local-folder-picker">
                    <div className="folder-browser-header">
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => browseLocalFolder(localFolderParent)}
                        disabled={!localFolderParent || localFolderLoading}
                        title="Up one folder"
                      >
                        <ChevronLeft size={15} />
                      </button>
                      <code>{localFolderCurrent || 'Computer'}</code>
                      <button type="button" className="ghost-button compact" onClick={() => setFolderPickerOpen(false)}>
                        Close
                      </button>
                    </div>
                    {localFolderError && <div className="error-message">{localFolderError}</div>}
                    {localFolderLoading && <div className="panel-state">Loading folders...</div>}
                    {!localFolderLoading && localFolders.length === 0 && <div className="panel-state">No child folders.</div>}
                    <div className="folder-list local-folder-list">
                      {localFolders.map((folder) => (
                        <button
                          type="button"
                          key={folder.path}
                          className="folder-list-item"
                          onClick={() => browseLocalFolder(folder.path)}
                        >
                          <FolderOpen size={14} />
                          <span>{folder.name}</span>
                          <small>{folder.path}</small>
                        </button>
                      ))}
                    </div>
                    <button
                      type="button"
                      className="folder-use-button"
                      onClick={useSelectedFolder}
                      disabled={!localFolderCurrent}
                    >
                      Use this folder
                    </button>
                  </div>
                )}
              </div>
            </section>

            <section className={`create-step-card ${folderReady ? 'active' : 'disabled'}`}>
              <div className="create-step-index">3</div>
              <div className="create-step-body">
                <div className="create-step-heading">
                  <h3>Description</h3>
                  <span>Optional</span>
                </div>
                <input
                  type="text"
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="Description"
                  disabled={!folderReady}
                  onKeyDown={(e) => e.key === 'Enter' && nameReady && folderReady && handleCreate()}
                />
              </div>
            </section>
          </div>
          <button
            className="primary-button"
            onClick={handleCreate}
            disabled={!nameReady || !folderReady || loading}
            title={!nameReady ? 'Enter a project name first' : !folderReady ? 'Choose an available data folder before creating the project' : undefined}
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
                {proj.data_root && <p className="flow-id">Data: {proj.data_root}</p>}
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
                {proj.data_root && (
                  <div className="detail-row">
                    <span className="detail-label">Data folder</span>
                    <span className="detail-value"><code>{proj.data_root}</code></span>
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
