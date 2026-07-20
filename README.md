# fnirs-flow

GUI-enabled fNIRS analysis toolbox and reproducibility framework. fnirs-flow
uses Flow graphs to orchestrate preprocessing, validation, execution, and
reproducibility workflows with an MNE-NIRS execution backend.

**v1.2.0** | 1068 source-tree tests passing | Python 3.10+

---

## Quick Start

### Installation

```bash
# Basic installation for core models and validation
pip install -e .

# Full installation with MNE-NIRS execution, API, and ML support
pip install -e ".[full]"

# Cedalion 26.5.1 backend support; requires Python 3.11+ and Git
pip install -e ".[full,cedalion]"

# Or use conda
conda env create -f environment.yml
```

### Backend Lazy Loading

fnirs-flow uses a lazy-loading architecture. Backends load only when needed:

| Scenario | Behavior |
|---|---|
| Import library or browse MethodAtoms | Does not load any backend (MNE/Cedalion) |
| Compile a Flow | Does not load backends; reads metadata only |
| Execute an MNE MethodAtom | Loads MNE-NIRS on demand |
| Execute a Cedalion MethodAtom | Loads Cedalion on demand |
| Cedalion is not installed | Returns a structured error; does not fall back to MNE and does not auto-install |

**Performance baseline**:

- Startup time for importing core modules: < 0.5s
- `describe()` / `is_available()` calls: < 0.1ms; 100 calls < 4ms
- Memory overhead increases only when a backend is imported

**Check backend status**:

```bash
python cli.py backends
```

### Three-Step Workflow

```bash
# 1. Validate a flow configuration
python cli.py validate configs/demo_task_glm_real.json

# 2. Compile it into an executable plan
python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo

# 3. Run the analysis; requires MNE-NIRS
python cli.py run outputs/demo --outdir outputs/demo
```

### Start the WebUI

```bash
# Option 1: production mode (recommended)
python cli.py webui
# The first run builds the frontend; later runs serve static files from FastAPI
# Visit http://127.0.0.1:8000

# Option 2: development mode with frontend hot reload
python cli.py webui --dev
# Starts both the Vite dev server and backend
# Frontend: http://localhost:3000
# Backend: http://127.0.0.1:8000

# Option 3: start frontend and backend separately
python -m uvicorn fnirs_flow.api.app:app --reload   # Backend :8000
cd webui && npm install && npm run dev               # Frontend :5173
```

**CLI parameters**:

- `--port PORT`: set the port; default is 8000
- `--host HOST`: set the bind address; default is 127.0.0.1
- `--dev`: enable development mode with frontend hot reload

---

## CLI Reference

| Command | Purpose | Example |
|---|---|---|
| `validate` | Validate a flow JSON file | `python cli.py validate configs/demo_task_glm_real.json` |
| `compile` | Compile a flow into plan, DAG, and manifests | `python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo` |
| `discover` | Discover and register public datasets | `python cli.py discover bids-nirs-tapping --outdir outputs/demo` |
| `dry-run` | Enumerate all subject/session/run combinations without execution | `python cli.py dry-run outputs/demo --outdir outputs/demo` |
| `run` | Execute analysis with MNE-NIRS | `python cli.py run outputs/demo --outdir outputs/demo` |
| `export` | Export a reproducibility package | `python cli.py export outputs/demo --outdir outputs/demo` |
| `rerun` | Rerun an imported package | `python cli.py rerun outputs/imported_package` |
| `import-homer3` | Import Homer3 configuration into fnirs-flow atoms | `python cli.py import-homer3 pipeline.cfg --outdir outputs/imported` |
| `import-analyzir` | Import an AnalyzIR R script into fnirs-flow atoms | `python cli.py import-analyzir pipeline.R --outdir outputs/imported` |
| `export-homer3` | Export atoms to Homer3 configuration | `python cli.py export-homer3 atoms.json --outdir outputs/homer3` |
| `export-analyzir` | Export atoms to an AnalyzIR R script | `python cli.py export-analyzir atoms.json --outdir outputs/analyzir` |
| `webui` | Start the WebUI server | `python cli.py webui` or `python cli.py webui --dev` |
| `backends` | Show backend status and capabilities | `python cli.py backends` |
| `verify-package` | Verify `.fnirsflow.zip` package integrity | `python cli.py verify-package package.fnirsflow.zip` |

`run` supports filters:

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

---

## Generative AI Integration

The root-level `ai_flow_generation_guide.md` defines prompt context for AI
systems. Provide that document as model context with a research description, and
the AI can generate a candidate `flow.json` analysis plan.

- AI outputs candidate FlowGraph JSON only, not executable code.
- The guide defines input fields such as research objective, data format,
  conditions, contrasts, and output schema.
- It includes 10 hard rules, including no validation bypass, no fabricated
  citations, and no PHI or private paths.
- Generated flows must still pass `validate_flow()` before execution.

**Usage**: provide the guide as a system prompt or context, attach your research
description, and ask the AI to output `flow.json`.

Example AI draft: `configs/ai_draft_task_glm.json`, a task GLM analysis plan
with `ai_generation` metadata and `requires_user_confirmation` items.

Related documents:

- Generation guide: `ai_flow_generation_guide.md`
- Example Flow: `configs/ai_draft_task_glm.json`
- Public API spec: `docs/specs/fnirs_flow_public_api.md`

---

## Project Structure

### Core Code: `fnirs_flow/`

| Package | Files | Purpose |
|---|---|---|
| **flow/** | `atoms.py` `models.py` `schemas.py` `snapshots.py` `migration.py` `migrations/` | Core Flow data models: `FlowAtom`, `AtomPort`, `FlowEdge`, `FlowGraph`, `ExecutionPlan`, `AIGenerationMetadata`; schema definitions and version migration |
| **compiler/** | `compiler.py` `execution_dag.py` `manifests.py` `hashing.py` | Compile FlowGraph into `plan.json`, `execution_dag.json`, and manifest files |
| **execution/** | `engine.py` `service.py` `batch.py` `operations.py` `batch_adapter.py` `provenance.py` `artifacts.py` `failures.py` | Execution engine for dry-run enumeration, real MNE-NIRS execution, batch processing, provenance, artifacts, and failure tracking |
| **adapters/** | `mne_nirs_adapter.py` `mne_nirs_steps.py` `mne_nirs_io.py` `qc_metrics.py` `roi_mapping.py` `homer3_export.py` `homer3_import.py` `analyzir_export.py` `analyzir_import.py` `cedalion_adapter.py` `cedalion_steps.py` `cedalion_capabilities.py` `cedalion_io.py` | MNE-NIRS adapter path, optional Cedalion backend adapter with 26 methods, QC metrics, ROI mapping, and Homer3/AnalyzIR import/export |
| **validation/** | `api.py` `graph.py` `adapters.py` `models.py` `state.py` `error_codes.py` | Graph validation, adapter compatibility, state validation, and structured error codes |
| **registry/** | `atom_templates.py` `node_templates.py` `node_library.py` `scenarios.py` `evidence_store.py` `evidence_config.py` `risk_rules.py` `presets.py` `methods.py` `combat_diagnostics.py` | MethodAtom template library with 113 templates, scenario router, Evidence Store, risk rules, and preset configuration |
| **security/** | `models.py` `validation.py` | Execution trust levels, capability manifests, import quarantine, and readiness checks |
| **exporters/** | `package_exporter.py` `package_importer.py` `outputs.py` `reports.py` `methods_report.py` `inclusion_audit.py` `reproducibility.py` `reportlets.py` | Reproducibility package import/export, report generation, and inclusion audit |
| **api/** | `app.py` `models.py` `projects.py` `__init__.py` | FastAPI backend for project CRUD, validation, compilation, discovery, execution, export REST APIs, and SSE progress updates |
| **data/** | `discovery.py` `manifest.py` `registry.py` | Public dataset discovery, data manifest handling, and data registration |

### Frontend: `webui/`

React + Vite frontend that calls the backend API through `src/api/client.ts`.

| Path | Purpose |
|---|---|
| `src/components/AppShell.tsx` | Application shell with navigation, toolbar, and status bar |
| `src/components/FlowCanvas.tsx` | Main Flow canvas component using React Flow |
| `src/components/Sidebar.tsx` | Sidebar for the MethodAtom library and configuration panels |
| `src/components/ParameterPanel.tsx` | Parameter editing panel |
| `src/components/ValidationPanel.tsx` | Validation results panel |
| `src/components/DagLayerPreview.tsx` | DAG layer preview |
| `src/pages/ProjectWorkspace.tsx` | Project workspace |
| `src/pages/FlowBuilder.tsx` | Flow builder |
| `src/pages/AtomLibrary.tsx` | MethodAtom library browser |
| `src/pages/DataWorkspace.tsx` | Data workspace |
| `src/pages/ValidationDashboard.tsx` | Validation dashboard |
| `src/pages/CompileSummary.tsx` | Compile summary |
| `src/pages/RunMonitor.tsx` | Execution monitor with SSE progress |
| `src/pages/ResultsWorkspace.tsx` | Results browser for artifacts, QC, channel, ROI, and group outputs |
| `src/pages/ExportPackage.tsx` | Package export with profile selection |
| `src/pages/ImportPackage.tsx` | Package import with quarantine management |
| `src/pages/SystemDiagnostics.tsx` | System diagnostics |

### Tests: `tests/`

The public release tree currently has 61 test modules with 958 passed and 5
skipped tests. The private development tree runs one additional dataset
discovery test when local sample data is available. Tests cover the core path:

| Test Files | Coverage |
|---|---|
| `test_flow_models.py` `test_flow_atom_models.py` | Flow data models |
| `test_graph_validation.py` `test_adapter_validation.py` `test_validation_api.py` | Graph validation and adapter compatibility |
| `test_compiler.py` `test_compile_gate.py` | Flow compilation |
| `test_mne_adapter.py` `test_sprint_c_adapter.py` | MNE-NIRS adapter |
| `test_homer3_bidirectional.py` | Homer3 bidirectional import/export |
| `test_analyzir_bidirectional.py` | AnalyzIR bidirectional import/export |
| `test_cross_backend_integration.py` | Homer3 to AnalyzIR cross-backend integration |
| `test_cli_adapters.py` | Adapter CLI end-to-end commands |
| `test_batch_runner.py` `test_execution_service.py` `test_sprint_b_execution.py` | Batch processing and execution engine |
| `test_api.py` `test_api_export.py` | REST API and export |
| `test_dataset_discovery.py` | Dataset discovery |
| `test_security_models.py` `test_security_validation.py` | Security models and quarantine |
| `test_state_validation.py` | State validation |
| `test_golden_outputs.py` `test_enhanced_reports.py` `test_reports_package.py` | Output artifacts and reports |
| `test_project_persistence.py` `test_snapshots.py` | Project persistence and snapshots |
| `test_schema_migration.py` `test_migration_roundtrip.py` `test_migration_roundtrip_v2.py` | Schema migration |
| `test_sprint_e_interop.py` | Interoperability |
| `test_dryrun_report.py` `test_qc_roi_outputs.py` | Dry-run reports and QC/ROI outputs |
| `test_node_library.py` `test_atom_library.py` `test_registry.py` | Template library and registry |
| `test_scenarios.py` | Scenario routing |
| `test_cli.py` | CLI commands |
| `test_smoke.py` | Smoke tests |

Run tests:

```bash
pytest                    # All tests
pytest tests/test_api.py  # One module
pytest -k "mne"           # Keyword filter
```

### Configuration: `configs/`

| File | Purpose |
|---|---|
| `demo_task_glm_real.json` | Main demo: complete task GLM flow, recommended starting point |
| `ai_draft_task_glm.json` | AI-generated task GLM candidate flow with `ai_generation` metadata |
| `demo_resting_state_flow.json` | Resting-state flow example |
| `demo_ml_validation_flow.json` | Machine-learning validation flow example |
| `demo_task_flow.json` | Basic task-state flow |
| `demo_task_flow_v0_2_method_atoms.json` | MethodAtom-based task-state flow |
| `evidence_backed_presets.json` | Preset parameters backed by literature evidence |
| `example_task_study.json` | Simple task-state study configuration |

### Schemas: `schemas/`

| File | Definition |
|---|---|
| `fnirs_flow.schema.json` | Main Flow JSON schema |
| `capability_manifest.schema.json` | Atom capability declaration schema |
| `risk_item.schema.json` | Risk item schema |
| `action_attempt.schema.json` | Action attempt record schema |
| `project_snapshot.schema.json` | Project snapshot schema |
| `readiness_result.schema.json` | Readiness check result schema |
| `literature_flow_evidence.schema.json` | Literature-to-Flow evidence mapping schema |

### Scripts: `scripts/`

| File | Purpose |
|---|---|
| `analyze_ds007738_qc_sensitivity.py` | ds007738 QC sensitivity analysis |
| `audit_ds007738_outputs.py` | ds007738 output audit |
| `benchmark_performance.py` | Performance benchmark script |
| `build_ds007738_exclusion_manifests.py` | ds007738 exclusion manifest builder |
| `compare_ds007738_golden_rerun.py` | ds007738 golden rerun comparison |
| `run_ds007738_full_analysis.py` | ds007738 full-pipeline analysis entry point |
| `sync_public_release.py` | Public release sync script |

### Documentation: `docs/`

| File | Purpose |
|---|---|
| `README.md` | Public documentation index |
| `specs/fnirs_flow_public_api.md` | Public API and package concepts |
| `specs/method_atom_parameter_ui_contract.md` | MethodAtom parameter UI metadata contract |
| `specs/package_profile_spec.md` | Submission, reviewer, and reproducibility profiles |
| `specs/mvp_task_glm_acceptance_checklist.md` | Task-GLM MVP acceptance checklist |

### Root Files

| File | Purpose |
|---|---|
| `cli.py` | CLI entry point for the `fnirs-flow` command |
| `pyproject.toml` | Python project configuration for dependencies, ruff, mypy, and pytest |
| `environment.yml` | Conda environment definition |
| `ai_flow_generation_guide.md` | Generative AI flow-generation prompt context specification |
| `CHANGELOG.md` | Version change log |
| `README.md` | This file |
| `PUBLIC_RELEASE.md` | Public release tree scope and exclusion strategy |
| `PUBLIC_RELEASE_MANIFEST.json` | Generated file list, sizes, and SHA-256 hashes |

---

## Execution Path

```text
flow.json
  -> validate (graph validation + adapter compatibility + backend capability checks)
  -> compile (plan.json + execution_dag.json + manifests + backend bindings)
  -> discover (dataset discovery + data_manifest.json)
  -> dry-run (enumerate subject/session/run)
  -> run (MNE-NIRS or Cedalion execution)
      read_run -> optical_density -> QC -> motion_correction -> filtering
      -> MBLL -> design_matrix -> GLM -> contrast -> channel_output -> roi_output
  -> export (reproducibility package)
```

**Backend selection**:

- **MNE-NIRS** (default): channel-space processing, GLM, and connectivity
  analysis
- **Cedalion** (optional): DOT, head models, signal decomposition, synthetic
  data, ML tools, and photogrammetry

**Mixed-backend Flow**: one Flow can mix MNE and Cedalion MethodAtoms. The system
switches backends automatically at MethodAtom granularity, and each backend
instance is reused during runtime.

---

## Core Concepts

| Term | Meaning |
|---|---|
| `MethodAtom` | Smallest composable method unit at literature or methodology granularity. The current library contains 113 templates. |
| `MethodAtomTemplate` | Reusable MethodAtom blueprint |
| `FlowAtom` | MethodAtom instance inside a Flow |
| `AtomPort` | MethodAtom input/output port |
| `FlowGraph` | Analysis workflow graph built from FlowAtoms and edges |
| `ExecutionPlan` | Executable plan compiled from a FlowGraph |
| `Evidence Store` | Structured storage for extracted literature evidence |
| `Scenario` | Research scenario router for `task`, `resting_state`, `real_world`, `hyperscanning`, and `machine_learning` |
| `Adapter` | Converter between upstream and downstream MethodAtom inputs and outputs |
| `Cedalion Adapter` | Optional Cedalion backend adapter with DOT, signal decomposition, synthetic data, and related backend-specific capabilities |
| `Reproducibility Package` | Transferable, reproducible analysis package that excludes raw data |

---

## Public Release Scope

This repository is a code-oriented public release tree. It includes source code,
the WebUI, tests, schemas, demo configs, public specs, release notes, licenses,
and generated release metadata.

It intentionally excludes non-release research worktables, local datasets,
generated analysis artifacts, reference checkouts, caches, platform metadata,
and submission working files. See `PUBLIC_RELEASE_MANIFEST.json` for the exact
published file list.

---

## Reference Specifications

- [NIRS-BIDS specification](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/near-infrared-spectroscopy.html)
- [BIDS Extended to fNIRS (Nature 2024)](https://www.nature.com/articles/s41597-024-04136-9)
- [fNIRS data standards (fNIRS.org)](https://fnirs.org/resources/data-analysis/standards/)
- [Best practices for fNIRS publications](https://www.spiedigitallibrary.org/journals/neurophotonics/volume-8/issue-01/012101/Best-practices-for-fNIRS-publications/10.1117/1.NPh.8.1.012101.full)
- [TDDR motion correction](https://pmc.ncbi.nlm.nih.gov/articles/PMC6230489/)
- [Short-channel regression](https://pmc.ncbi.nlm.nih.gov/articles/PMC7523733/)
- [Demographic reporting in fNIRS](https://pmc.ncbi.nlm.nih.gov/articles/PMC10203458/)
- [fNIRS reproducibility (Nature 2025)](https://www.nature.com/articles/s42003-025-08412-1)
- [MNE-NIRS preprocessing examples](https://mne.tools/stable/auto_examples/preprocessing/fnirs_artifact_removal.html)
