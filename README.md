# fnirs-flow

GUI-enabled fNIRS analysis toolbox and reproducibility framework. fnirs-flow uses MethodAtom-based Flow graphs to organize preprocessing, validation, execution, review, and reproducible package export for fNIRS studies. The default execution path is powered by MNE-NIRS, with optional Cedalion backend support.

**v1.2.0** | 1068 source-tree tests passing | Python 3.10+

## Quick Start

### Installation

```bash
# Core models and validation only
pip install -e .

# Full install with MNE-NIRS execution, API, and ML support
pip install -e ".[full]"

# Full install with the optional Cedalion 26.5.1 backend
# Requires Python 3.11+ and Git.
pip install -e ".[full,cedalion]"

# Or use conda
conda env create -f environment.yml
```

### Lazy Backend Loading

fnirs-flow loads execution backends only when they are needed.

| Scenario | Behavior |
|---|---|
| Import the package or browse MethodAtoms | Does not load MNE or Cedalion |
| Compile a Flow | Does not load a backend; reads metadata only |
| Execute an MNE MethodAtom | Loads MNE-NIRS on demand |
| Execute a Cedalion MethodAtom | Loads Cedalion on demand |
| Cedalion is not installed | Returns a structured error; does not fall back to MNE or install packages automatically |

Performance baseline:

- Core import startup: `< 0.5s`
- `describe()` / `is_available()` calls: `< 0.1ms` per call, with 100 calls under 4 ms
- Backend memory overhead is incurred only when a backend is imported

Check backend status:

```bash
python cli.py backends
```

### Three-Step CLI Workflow

```bash
# 1. Validate a Flow configuration
python cli.py validate configs/demo_task_glm_real.json

# 2. Compile it into an executable plan
python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo

# 3. Run the analysis
python cli.py run outputs/demo --outdir outputs/demo
```

### Start the WebUI

```bash
# Production mode
python cli.py webui
# First launch builds the frontend; later launches serve static files from FastAPI.
# Open http://127.0.0.1:8000

# Development mode with frontend hot reload
python cli.py webui --dev
# Frontend: http://localhost:3000
# Backend:  http://127.0.0.1:8000

# Start backend and frontend separately
python -m uvicorn fnirs_flow.api.app:app --reload   # backend on :8000
cd webui && npm install && npm run dev               # frontend on :5173
```

CLI options:

- `--port PORT`: server port, default `8000`
- `--host HOST`: bind host, default `127.0.0.1`
- `--dev`: enable Vite development mode

## WebUI Tutorial

For a screenshot-based walkthrough, see [Task GLM WebUI Tutorial](docs/tutorials/task_glm_webui_tutorial.md). It covers project creation, Flow loading, validation, compilation, data discovery, dry run, execution, results review, export, and system diagnostics.

## CLI Reference

| Command | Purpose | Example |
|---|---|---|
| `validate` | Validate a Flow JSON file | `python cli.py validate configs/demo_task_glm_real.json` |
| `compile` | Compile a Flow into plan, DAG, and manifests | `python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo` |
| `discover` | Discover and register a public dataset | `python cli.py discover bids-nirs-tapping --outdir outputs/demo` |
| `dry-run` | Enumerate subject/session/run units without execution | `python cli.py dry-run outputs/demo --outdir outputs/demo` |
| `run` | Execute an analysis through MNE-NIRS or Cedalion | `python cli.py run outputs/demo --outdir outputs/demo` |
| `export` | Export a reproducibility package | `python cli.py export outputs/demo --outdir outputs/demo` |
| `rerun` | Rerun an imported package | `python cli.py rerun outputs/imported_package` |
| `import-homer3` | Import a Homer3 config as fnirs-flow atoms | `python cli.py import-homer3 pipeline.cfg --outdir outputs/imported` |
| `import-analyzir` | Import an AnalyzIR R script as fnirs-flow atoms | `python cli.py import-analyzir pipeline.R --outdir outputs/imported` |
| `export-homer3` | Export atoms to a Homer3 config | `python cli.py export-homer3 atoms.json --outdir outputs/homer3` |
| `export-analyzir` | Export atoms to an AnalyzIR R script | `python cli.py export-analyzir atoms.json --outdir outputs/analyzir` |
| `webui` | Start the WebUI server | `python cli.py webui` or `python cli.py webui --dev` |
| `backends` | Show backend status and capabilities | `python cli.py backends` |
| `verify-package` | Verify a `.fnirsflow.zip` package | `python cli.py verify-package package.fnirsflow.zip` |

`run` supports participant, session, and run filters:

```bash
python cli.py run outputs/demo --outdir outputs/demo \
  --participant-label sub-01 sub-02 \
  --session-label ses-01 \
  --run-label run-01
```

`export` supports three profiles:

```bash
python cli.py export outputs/demo --outdir outputs/demo --profile reproducibility_package
python cli.py export outputs/demo --outdir outputs/demo --profile submission_package
python cli.py export outputs/demo --outdir outputs/demo --profile reviewer_package
```

## Generative AI Flow Drafting

`ai_flow_generation_guide.md` defines the prompt context for AI systems that draft candidate `flow.json` analysis plans.

- The AI outputs a candidate FlowGraph JSON, not executable code.
- The guide defines expected input fields, output schema, and safety rules.
- Drafts must not bypass validation, invent literature claims, include PHI, or include private local paths.
- A generated Flow must pass `validate_flow()` before execution.

Example draft: `configs/ai_draft_task_glm.json`.

## Execution Chain

```text
flow.json
  -> validate (graph validation, adapter compatibility, backend capability checks)
  -> compile (plan.json, execution_dag.json, manifests, backend bindings)
  -> discover (dataset discovery and data_manifest.json)
  -> dry-run (subject/session/run enumeration)
  -> run (MNE-NIRS or Cedalion execution)
      read_run -> optical_density -> QC -> motion_correction -> filtering
      -> MBLL -> design_matrix -> GLM -> contrast -> channel_output -> roi_output
  -> export (reproducibility package)
```

Backend selection:

- **MNE-NIRS** is the default backend for channel-space processing, GLM, and connectivity workflows.
- **Cedalion** is optional and adds DOT, head modeling, signal decomposition, synthetic data, ML utilities, and photogrammetry-oriented operations.
- Mixed-backend Flows are supported at MethodAtom granularity. Backend instances are reused during execution.

## Core Concepts

| Term | Meaning |
|---|---|
| `MethodAtom` | Minimal composable method unit at the literature/methodology level |
| `MethodAtomTemplate` | Reusable MethodAtom blueprint |
| `FlowAtom` | MethodAtom instance inside a Flow |
| `AtomPort` | Input or output port on a MethodAtom |
| `FlowGraph` | Directed analysis graph made from FlowAtoms and edges |
| `ExecutionPlan` | Executable plan compiled from a FlowGraph |
| `Evidence Store` | Structured store for extracted methodological evidence |
| `Scenario` | Study-scenario router for task, resting-state, real-world, hyperscanning, and ML workflows |
| `Adapter` | Connector that transforms or validates data between MethodAtoms |
| `Cedalion Adapter` | Optional backend adapter for Cedalion-specific capabilities |
| `Reproducibility Package` | Portable analysis package that excludes raw data by default |

## Repository Map

### Core Package: `fnirs_flow/`

| Subpackage | Purpose |
|---|---|
| `flow/` | Flow data models, schemas, snapshots, and migrations |
| `compiler/` | FlowGraph to `plan.json`, `execution_dag.json`, and manifest compilation |
| `execution/` | Dry run, batch execution, provenance, artifacts, and failure tracking |
| `adapters/` | MNE-NIRS, Cedalion, Homer3, and AnalyzIR adapters |
| `validation/` | Graph validation, adapter compatibility, state validation, and typed error codes |
| `registry/` | MethodAtom templates, scenarios, evidence store, risk rules, and presets |
| `security/` | Trust levels, capability manifests, import quarantine, and readiness checks |
| `exporters/` | Package export/import, reports, methods reports, and reproducibility helpers |
| `api/` | FastAPI project, validation, compile, discovery, execution, export, and SSE endpoints |
| `data/` | Public dataset discovery, data manifests, and dataset registry |

### WebUI: `webui/`

React + Vite frontend using `src/api/client.ts` for backend API calls.

| Path | Purpose |
|---|---|
| `src/components/AppShell.tsx` | Application shell, navigation, toolbar, and status indicators |
| `src/components/FlowCanvas.tsx` | Main React Flow canvas |
| `src/components/Sidebar.tsx` | MethodAtom library and configuration sidebar |
| `src/components/ParameterPanel.tsx` | Node parameter editor |
| `src/components/ValidationPanel.tsx` | Validation result viewer |
| `src/components/DagLayerPreview.tsx` | DAG layer preview |
| `src/pages/ProjectWorkspace.tsx` | Project workspace |
| `src/pages/FlowBuilder.tsx` | Flow builder |
| `src/pages/AtomLibrary.tsx` | MethodAtom library browser |
| `src/pages/DataWorkspace.tsx` | Data workspace |
| `src/pages/ValidationDashboard.tsx` | Validation dashboard |
| `src/pages/CompileSummary.tsx` | Compile summary |
| `src/pages/RunMonitor.tsx` | Run monitor with SSE progress |
| `src/pages/ResultsWorkspace.tsx` | Artifact, QC, channel, ROI, and group results |
| `src/pages/ExportPackage.tsx` | Package export with profile selection |
| `src/pages/ImportPackage.tsx` | Package import and quarantine handling |
| `src/pages/SystemDiagnostics.tsx` | Runtime and backend diagnostics |

### Configs and Schemas

| Area | Contents |
|---|---|
| `configs/` | Demo task GLM, AI draft, resting-state, ML validation, MethodAtom, preset, and study configs |
| `schemas/` | Flow, capability manifest, risk item, action attempt, project snapshot, readiness, and literature evidence schemas |

### Tests

The public release contains focused source-tree tests for models, validation, compilation, adapters, execution, package export/import, project persistence, schema migration, API behavior, node libraries, and smoke coverage.

Run tests:

```bash
pytest
pytest tests/test_api.py
pytest -k "mne"
```

## Public Documentation

- [Documentation Index](docs/README.md)
- [Task GLM WebUI Tutorial](docs/tutorials/task_glm_webui_tutorial.md)
- [Public API Contract](docs/specs/fnirs_flow_public_api.md)
- [Package Profile Specification](docs/specs/package_profile_spec.md)
- [MVP Task GLM Acceptance Checklist](docs/specs/mvp_task_glm_acceptance_checklist.md)
- [AI Flow Generation Guide](ai_flow_generation_guide.md)
- [Third-Party Notices](THIRD_PARTY_NOTICES.md)
- [Changelog](CHANGELOG.md)

## Reference Standards

- [NIRS-BIDS specification](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/near-infrared-spectroscopy.html)
- [BIDS Extended to fNIRS (Nature 2024)](https://www.nature.com/articles/s41597-024-04136-9)
- [fNIRS data standards (fNIRS.org)](https://fnirs.org/resources/data-analysis/standards/)
- [Best practices for fNIRS publications](https://www.spiedigitallibrary.org/journals/neurophotonics/volume-8/issue-01/012101/Best-practices-for-fNIRS-publications/10.1117/1.NPh.8.1.012101.full)
- [TDDR motion correction](https://pmc.ncbi.nlm.nih.gov/articles/PMC6230489/)
- [Short-channel regression](https://pmc.ncbi.nlm.nih.gov/articles/PMC7523733/)
- [Demographic reporting in fNIRS](https://pmc.ncbi.nlm.nih.gov/articles/PMC10203458/)
- [fNIRS reproducibility (Nature 2025)](https://www.nature.com/articles/s42003-025-08412-1)
- [MNE-NIRS preprocessing examples](https://mne.tools/stable/auto_examples/preprocessing/fnirs_artifact_removal.html)
