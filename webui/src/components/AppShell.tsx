import { useEffect, useCallback, useState } from 'react';
import { Outlet, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useShallow } from 'zustand/react/shallow';
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  Circle,
  Database,
  Download,
  FileCheck2,
  FlaskConical,
  FolderKanban,
  Loader2,
  MoreHorizontal,
  Play,
  Save,
  Settings,
  X,
} from 'lucide-react';
import { useStore } from '../store';
import { subscribeProgress } from '../api/client';
import type { Project } from '../api/client';

type NavId = 'projects' | 'flow' | 'atoms' | 'data' | 'checks' | 'runs' | 'results' | 'compile' | 'package' | 'import' | 'system';

const navItems: Array<{ id: NavId; label: string; icon: typeof FolderKanban }> = [
  { id: 'projects', label: 'Projects', icon: FolderKanban },
  { id: 'flow', label: 'Flow', icon: Boxes },
  { id: 'data', label: 'Data', icon: Database },
  { id: 'checks', label: 'Checks', icon: FileCheck2 },
  { id: 'compile', label: 'Compile', icon: FileCheck2 },
  { id: 'runs', label: 'Runs', icon: Play },
  { id: 'results', label: 'Results', icon: CheckCircle2 },
  { id: 'package', label: 'Export', icon: Download },
];

const moreNavItems: Array<{ id: NavId; label: string; icon: typeof FolderKanban }> = [
  { id: 'atoms', label: 'Atom Library', icon: Boxes },
  { id: 'import', label: 'Import', icon: Download },
  { id: 'system', label: 'System', icon: Settings },
];

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { id: projectId } = useParams();
  const [moreOpen, setMoreOpen] = useState(false);
  const [desktopViewport, setDesktopViewport] = useState(() => {
    if (typeof window === 'undefined') return true;
    return window.matchMedia('(min-width: 900px)').matches;
  });

  const project = useStore((s) => s.project);
  const loading = useStore((s) => s.loading);
  const error = useStore((s) => s.error);
  const clearError = useStore((s) => s.clearError);
  const status = useStore(useShallow((s) => s.projectStatus()));
  const saveFlow = useStore((s) => s.saveFlow);
  const validate = useStore((s) => s.validate);
  const compile = useStore((s) => s.compile);
  const execute = useStore((s) => s.execute);
  const readOnly = useStore((s) => s.importStatus?.read_only ?? false);

  // Auto-load project when URL has :id
  const selectProject = useStore((s) => s.selectProject);
  const projects = useStore((s) => s.projects);

  useEffect(() => {
    if (projectId && (!project || project.id !== projectId)) {
      const found = projects.find((p: Project) => p.id === projectId);
      if (found) {
        selectProject(found);
      }
    }
  }, [projectId, project, projects, selectProject]);

  useEffect(() => {
    const query = window.matchMedia('(min-width: 900px)');
    const handleChange = () => setDesktopViewport(query.matches);
    handleChange();
    query.addEventListener('change', handleChange);
    return () => query.removeEventListener('change', handleChange);
  }, []);

  // Subscribe to SSE progress
  useEffect(() => {
    if (!project) return;
    const unsubscribe = subscribeProgress(project.id, (event) => {
      useStore.setState((prev) => ({
        progressEvents: [...prev.progressEvents.slice(-50), event],
      }));
    });
    return unsubscribe;
  }, [project]);

  const getActiveNav = useCallback((): NavId => {
    const path = location.pathname;
    if (path === '/' || path.startsWith('/projects') && !projectId) return 'projects';
    if (path.endsWith('/flow')) return 'flow';
    if (path.endsWith('/atoms')) return 'atoms';
    if (path.endsWith('/data')) return 'data';
    if (path.endsWith('/checks')) return 'checks';
    if (path.endsWith('/runs')) return 'runs';
    if (path.endsWith('/results')) return 'results';
    if (path.endsWith('/compile')) return 'compile';
    if (path.endsWith('/package')) return 'package';
    if (path.endsWith('/import')) return 'import';
    if (path.startsWith('/system')) return 'system';
    return 'projects';
  }, [location.pathname, projectId]);

  const activeNav = getActiveNav();
  const moreActive = moreNavItems.some((item) => item.id === activeNav);
  const isSuccessNotice = error
    ? ['Fork created', 'Flow saved', 'Execution cancelled'].includes(error.message)
    : false;

  const handleNavClick = (navId: NavId) => {
    setMoreOpen(false);
    if (navId === 'projects') {
      navigate('/projects');
    } else if (navId === 'system') {
      navigate('/system');
    } else {
      const targetProjectId = projectId || project?.id;
      if (targetProjectId) navigate(`/projects/${targetProjectId}/${navId}`);
    }
  };

  const canOpen = (navId: NavId): boolean => {
    if (navId === 'projects' || navId === 'system') return true;
    if (!status.selected) return false;
    return true;
  };

  return (
    <div className="app shell">
      <div className="mobile-unsupported" role="alert">
        <div>
          <span className="mobile-unsupported-kicker">Desktop required</span>
          <h1>Open fnirs-flow on a larger screen</h1>
          <p>
            The workflow canvas, checklist, validation, and results tables require a desktop-width workspace.
          </p>
        </div>
      </div>
      {desktopViewport && (
        <>
          <aside className="app-rail">
            <button className="brand-mark" onClick={() => navigate('/projects')} title="Projects">
              <FlaskConical size={20} />
            </button>
            <nav className="rail-nav" aria-label="Main navigation">
              {navItems.map((item) => {
                const Icon = item.icon;
                const disabled = !canOpen(item.id);
                return (
                  <button
                    key={item.id}
                    className={activeNav === item.id ? 'active' : ''}
                    onClick={() => !disabled && handleNavClick(item.id)}
                    disabled={disabled}
                    title={item.label}
                    aria-label={item.label}
                    aria-current={activeNav === item.id ? 'page' : undefined}
                  >
                    <Icon size={18} />
                  </button>
                );
              })}
              <div className="rail-more">
                <button
                  className={moreActive || moreOpen ? 'active' : ''}
                  onClick={() => setMoreOpen((open) => !open)}
                  title="More"
                  aria-label="More navigation"
                  aria-expanded={moreOpen}
                >
                  <MoreHorizontal size={18} />
                </button>
                {moreOpen && (
                  <div className="rail-more-menu" role="menu">
                    {moreNavItems.map((item) => {
                      const Icon = item.icon;
                      const disabled = !canOpen(item.id);
                      return (
                        <button
                          key={item.id}
                          className={activeNav === item.id ? 'active' : ''}
                          onClick={() => !disabled && handleNavClick(item.id)}
                          disabled={disabled}
                          role="menuitem"
                          aria-current={activeNav === item.id ? 'page' : undefined}
                        >
                          <Icon size={16} />
                          <span>{item.label}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </nav>
          </aside>

          <section className="app-workbench">
            <header className="flow-toolbar">
              <div className="flow-title-block">
                <span className="toolbar-kicker">fnirs-flow</span>
                <h1>{project ? project.name : 'Project Workspace'}</h1>
              </div>
              <div className="workflow-steps">
                <Step label="Flow" done={status.flowSaved} />
                <Step label="Validated" done={status.validated} />
                <Step label="Compiled" done={status.compiled} />
                <Step label="Data" done={status.dataDiscovered} />
                <Step label="Executed" done={status.executed} />
              </div>
              <div className="toolbar-actions">
                {project && (
                  <>
                    <button className="ghost-button" onClick={saveFlow} disabled={loading || readOnly} title={readOnly ? 'Fork the imported package before editing' : 'Save flow'}>
                      <Save size={16} />
                      <span>Save</span>
                    </button>
                    <button className="ghost-button" onClick={validate} disabled={loading} title="Validate flow">
                      {loading ? <Loader2 size={16} className="spin" /> : <FileCheck2 size={16} />}
                      <span>Validate</span>
                    </button>
                    <button className="ghost-button" onClick={compile} disabled={loading || readOnly} title={readOnly ? 'Fork the imported package before compiling' : 'Compile flow'}>
                      <Save size={16} />
                      <span>Compile</span>
                    </button>
                    <button
                      className="primary-button"
                      onClick={execute}
                      disabled={loading || !status.compiled || !status.dataDiscovered || status.hasFatalRisk}
                      title={status.hasFatalRisk ? 'Cannot execute: fatal validation risks detected' : 'Execute project'}
                    >
                      <Play size={16} />
                      <span>Run</span>
                    </button>
                  </>
                )}
              </div>
            </header>

            {error && (
              <div className={`toast-banner ${isSuccessNotice ? 'success' : 'error'}`}>
                {isSuccessNotice ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
                <div>
                  <strong>{error.message}</strong>
                  {error.detail && <span>{error.detail}</span>}
                </div>
                <button onClick={clearError} aria-label="Dismiss">
                  <X size={16} />
                </button>
              </div>
            )}

            <main className="app-main">
              <Outlet />
            </main>
          </section>
        </>
      )}
    </div>
  );
}

function Step({ label, done }: { label: string; done: boolean }) {
  return (
    <span className={`workflow-step ${done ? 'done' : ''}`}>
      {done ? <CheckCircle2 size={13} /> : <Circle size={13} />}
      {label}
    </span>
  );
}

// Project loader for /projects/:id routes
export function ProjectLoader() {
  const { id } = useParams();
  const project = useStore((s) => s.project);
  const projects = useStore((s) => s.projects);
  const selectProject = useStore((s) => s.selectProject);
  const loadProjects = useStore((s) => s.loadProjects);

  useEffect(() => {
    if (!id) return;
    if (project && project.id === id) return;

    if (projects.length === 0) {
      loadProjects().then(() => {
        const found = useStore.getState().projects.find((p: Project) => p.id === id);
        if (found) selectProject(found);
      });
    } else {
      const found = projects.find((p: Project) => p.id === id);
      if (found) selectProject(found);
    }
  }, [id, project, projects, selectProject, loadProjects]);

  return <Outlet />;
}
