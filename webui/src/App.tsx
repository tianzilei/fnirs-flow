import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppShell, ProjectLoader } from './components/AppShell';

const ProjectWorkspace = lazy(() => import('./pages/ProjectWorkspace').then(
  ({ ProjectWorkspace }) => ({ default: ProjectWorkspace }),
));
const FlowBuilder = lazy(() => import('./pages/FlowBuilder').then(
  ({ FlowBuilder }) => ({ default: FlowBuilder }),
));
const AtomLibrary = lazy(() => import('./pages/AtomLibrary').then(
  ({ AtomLibrary }) => ({ default: AtomLibrary }),
));
const DataWorkspace = lazy(() => import('./pages/DataWorkspace').then(
  ({ DataWorkspace }) => ({ default: DataWorkspace }),
));
const ValidationDashboard = lazy(() => import('./pages/ValidationDashboard').then(
  ({ ValidationDashboard }) => ({ default: ValidationDashboard }),
));
const RunMonitor = lazy(() => import('./pages/RunMonitor').then(
  ({ RunMonitor }) => ({ default: RunMonitor }),
));
const CompileSummary = lazy(() => import('./pages/CompileSummary').then(
  ({ CompileSummary }) => ({ default: CompileSummary }),
));
const ResultsWorkspace = lazy(() => import('./pages/ResultsWorkspace').then(
  ({ ResultsWorkspace }) => ({ default: ResultsWorkspace }),
));
const ExportPackage = lazy(() => import('./pages/ExportPackage').then(
  ({ ExportPackage }) => ({ default: ExportPackage }),
));
const ImportPackage = lazy(() => import('./pages/ImportPackage').then(
  ({ ImportPackage }) => ({ default: ImportPackage }),
));
const SystemDiagnostics = lazy(() => import('./pages/SystemDiagnostics').then(
  ({ SystemDiagnostics }) => ({ default: SystemDiagnostics }),
));

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="loading-state">Loading...</div>}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/projects" replace />} />
            <Route path="projects" element={<ProjectWorkspace />} />
            <Route path="projects/:id" element={<ProjectLoader />}>
              <Route index element={<Navigate to="flow" replace />} />
              <Route path="flow" element={<FlowBuilder />} />
              <Route path="atoms" element={<AtomLibrary />} />
              <Route path="data" element={<DataWorkspace />} />
              <Route path="checks" element={<ValidationDashboard />} />
              <Route path="runs" element={<RunMonitor />} />
              <Route path="results" element={<ResultsWorkspace />} />
              <Route path="compile" element={<CompileSummary />} />
              <Route path="package" element={<ExportPackage />} />
              <Route path="import" element={<ImportPackage />} />
            </Route>
            <Route path="system" element={<SystemDiagnostics />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
