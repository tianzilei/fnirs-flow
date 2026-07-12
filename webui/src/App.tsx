import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppShell, ProjectLoader } from './components/AppShell';
import { ProjectWorkspace } from './pages/ProjectWorkspace';
import { FlowBuilder } from './pages/FlowBuilder';
import { AtomLibrary } from './pages/AtomLibrary';
import { DataWorkspace } from './pages/DataWorkspace';
import { ValidationDashboard } from './pages/ValidationDashboard';
import { RunMonitor } from './pages/RunMonitor';
import { CompileSummary } from './pages/CompileSummary';
import { ResultsWorkspace } from './pages/ResultsWorkspace';
import { ExportPackage } from './pages/ExportPackage';
import { ImportPackage } from './pages/ImportPackage';
import { SystemDiagnostics } from './pages/SystemDiagnostics';

export default function App() {
  return (
    <BrowserRouter>
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
    </BrowserRouter>
  );
}
