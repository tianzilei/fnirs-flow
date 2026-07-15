# fnirs-flow

fnirs-flow is a GUI-enabled fNIRS analysis toolbox and reproducibility
framework. It lets users describe an analysis as a FlowGraph, validate it,
compile it into an execution plan, run supported MNE-NIRS workflows, and export
portable reproducibility packages.

**Release:** v1.2.0

**Validation baseline:** public tree 1067 passed, 5 skipped

**Python:** 3.10+

## What Is Included

This public repository contains the code-oriented release tree:

- Python package and CLI entry point
- FastAPI backend and React/Vite WebUI source
- JSON schemas, demo configs, and tests
- Selected public API and package profile specifications
- License and third-party notices

It intentionally does not include manuscript drafts, private audit logs, local
sample data, generated outputs, literature extraction workspaces, or reference
repository mirrors. See `PUBLIC_RELEASE.md` for the exact public-release scope.

## Quick Start

### Install

```bash
# Core models, validation, and CLI
pip install -e .

# Full runtime, including API and MNE-NIRS execution support
pip install -e ".[full]"

# Optional Cedalion backend support, requiring Python 3.11+ and Git
pip install -e ".[full,cedalion]"

# Or create the conda environment
conda env create -f environment.yml
```

### Validate, Compile, Run

```bash
# 1. Validate a flow configuration
python cli.py validate configs/demo_task_glm_real.json

# 2. Compile it into plan.json, execution_dag.json, and manifests
python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo

# 3. Execute the compiled plan, if MNE-NIRS dependencies are available
python cli.py run outputs/demo --outdir outputs/demo
```

Generated `outputs/` directories are runtime artifacts and are not tracked in
the public repository.

### Start The WebUI

```bash
# Production mode: build frontend if needed, then serve it from FastAPI
python cli.py webui
# Visit http://127.0.0.1:8000

# Development mode: run Vite with backend proxy
python cli.py webui --dev

# Or start backend and frontend separately
python -m uvicorn fnirs_flow.api.app:app --reload
cd webui && npm install && npm run dev
```

Useful options:

| Option | Meaning |
|---|---|
| `--port PORT` | Backend port, default `8000` |
| `--host HOST` | Bind host, default `127.0.0.1` |
| `--dev` | Enable frontend hot reload |

## CLI Reference

| Command | Purpose | Example |
|---|---|---|
| `validate` | Validate flow JSON | `python cli.py validate configs/demo_task_glm_real.json` |
| `compile` | Compile flow to plan, DAG, and manifests | `python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo` |
| `discover` | Discover and register a public dataset | `python cli.py discover bids-nirs-tapping --outdir outputs/demo` |
| `dry-run` | Enumerate subject/session/run units without executing | `python cli.py dry-run outputs/demo --outdir outputs/demo` |
| `run` | Execute an MNE-NIRS-backed plan | `python cli.py run outputs/demo --outdir outputs/demo` |
| `export` | Export a reproducibility package | `python cli.py export outputs/demo --outdir outputs/demo` |
| `rerun` | Rerun an imported package | `python cli.py rerun outputs/imported_package` |
| `import-homer3` | Import Homer3 config into fnirs-flow atoms | `python cli.py import-homer3 pipeline.cfg --outdir outputs/imported` |
| `import-analyzir` | Import AnalyzIR R script into fnirs-flow atoms | `python cli.py import-analyzir pipeline.R --outdir outputs/imported` |
| `export-homer3` | Export atoms to Homer3 config | `python cli.py export-homer3 atoms.json --outdir outputs/homer3` |
| `export-analyzir` | Export atoms to AnalyzIR R script | `python cli.py export-analyzir atoms.json --outdir outputs/analyzir` |
| `webui` | Start the WebUI server | `python cli.py webui` |
| `backends` | Show backend availability and capabilities | `python cli.py backends` |
| `verify-package` | Verify a `.fnirsflow.zip` package | `python cli.py verify-package package.fnirsflow.zip` |

`run` supports participant/session/run filters:

```bash
python cli.py run outputs/demo --outdir outputs/demo \
  --participant-label sub-01 sub-02 \
  --session-label ses-01 \
  --run-label run-01
```

`export` supports these package profiles:

```bash
python cli.py export outputs/demo --outdir outputs/demo --profile reproducibility_package
python cli.py export outputs/demo --outdir outputs/demo --profile submission_package
python cli.py export outputs/demo --outdir outputs/demo --profile reviewer_package
```

## Backend Loading

fnirs-flow uses lazy backend loading:

| Scenario | Behavior |
|---|---|
| Import core package or browse MethodAtoms | Does not load MNE or Cedalion |
| Compile a FlowGraph | Reads metadata only |
| Execute MNE MethodAtoms | Loads MNE-NIRS on demand |
| Execute Cedalion MethodAtoms | Loads Cedalion on demand |
| Cedalion missing | Returns a structured backend error; no fallback and no auto-install |

Check the current environment:

```bash
python cli.py backends
```

## Core Concepts

| Term | Meaning |
|---|---|
| `MethodAtom` | Smallest composable method unit. The current library contains 113 templates. |
| `FlowAtom` | A MethodAtom instance inside a FlowGraph. |
| `FlowGraph` | Analysis graph made of FlowAtoms and directed edges. |
| `ExecutionPlan` | Compiled plan generated from a FlowGraph. |
| `Adapter` | Compatibility layer between MethodAtom inputs and outputs. |
| `Backend` | Runtime implementation, currently MNE-NIRS by default and Cedalion as optional support. |
| `Reproducibility Package` | Portable package for review, relinking, and rerun without bundling raw data. |

## Project Layout

### Python Package

| Path | Purpose |
|---|---|
| `fnirs_flow/flow/` | FlowAtom, FlowGraph, schema migration, snapshots |
| `fnirs_flow/compiler/` | FlowGraph to execution plan, DAG, manifests |
| `fnirs_flow/execution/` | Batch execution, provenance, artifacts, failure records |
| `fnirs_flow/adapters/` | MNE-NIRS, Cedalion, Homer3, AnalyzIR, QC, ROI mapping |
| `fnirs_flow/validation/` | Graph, adapter, state, and readiness validation |
| `fnirs_flow/registry/` | MethodAtom templates, scenarios, presets, evidence-backed metadata |
| `fnirs_flow/security/` | Trust model, quarantine validation, capability manifests |
| `fnirs_flow/exporters/` | Package export/import, verification, reports |
| `fnirs_flow/api/` | FastAPI backend and project APIs |
| `fnirs_flow/data/` | Public dataset discovery and data manifests |

### WebUI

The WebUI is a React + Vite application under `webui/`.

| Path | Purpose |
|---|---|
| `src/components/FlowCanvas.tsx` | Flow graph canvas |
| `src/components/ParameterPanel.tsx` | Atom parameter editing |
| `src/components/ValidationPanel.tsx` | Validation results |
| `src/components/DesignHistoryPanel.tsx` | FlowVCS design history |
| `src/components/AIDraftReviewPanel.tsx` | AI draft review and confirmation |
| `src/pages/ProjectWorkspace.tsx` | Project workspace |
| `src/pages/FlowBuilder.tsx` | Flow builder |
| `src/pages/DataWorkspace.tsx` | Data discovery and binding |
| `src/pages/RunMonitor.tsx` | Execution monitor |
| `src/pages/ResultsWorkspace.tsx` | Artifact and result browsing |
| `src/pages/ExportPackage.tsx` | Package export |
| `src/pages/ImportPackage.tsx` | Package import and quarantine handling |
| `src/pages/SystemDiagnostics.tsx` | Backend and environment diagnostics |

### Public Docs

| File | Purpose |
|---|---|
| `docs/README.md` | Public documentation index |
| `docs/specs/fnirs_flow_public_api.md` | Public API and model contract |
| `docs/specs/package_profile_spec.md` | Package profile behavior |
| `docs/specs/mvp_task_glm_acceptance_checklist.md` | Task GLM user-path acceptance checklist |
| `ai_flow_generation_guide.md` | Prompt/context guide for generating candidate FlowGraph JSON |

## Generative AI Drafts

`ai_flow_generation_guide.md` defines how an AI assistant can draft candidate
FlowGraph JSON. The draft contract is deliberately conservative:

- AI produces candidate FlowGraph JSON, not executable code.
- High-impact parameters remain in `requires_user_confirmation`.
- Drafts must pass fnirs-flow validation before execution.
- No PHI, private paths, credentials, or invented evidence claims may be used.

Example draft: `configs/ai_draft_task_glm.json`.

## Testing And Validation

```bash
python -m pytest tests -q
python -m ruff check fnirs_flow cli.py scripts tests

cd webui
npm ci
npm run build
```

Release v1.2.0 public-tree validation on 2026-07-15:

| Check | Result |
|---|---|
| Pytest | 1067 passed, 5 skipped |
| Ruff | passed |
| WebUI build | passed |
| npm audit | 0 vulnerabilities |
| Line endings | LF-normalized; no tracked `w/crlf` or `w/mixed` files |

## Execution Flow

```text
flow.json
  -> validate
  -> compile
  -> discover
  -> dry-run
  -> run
  -> export
```

The task-GLM execution path is:

```text
read_run -> optical_density -> QC -> motion_correction -> filtering
  -> MBLL -> design_matrix -> GLM -> contrast
  -> channel_output -> roi_output
```

## Reference Standards

- [NIRS-BIDS specification](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/near-infrared-spectroscopy.html)
- [BIDS Extended to fNIRS](https://www.nature.com/articles/s41597-024-04136-9)
- [fNIRS data standards](https://fnirs.org/resources/data-analysis/standards/)
- [Best practices for fNIRS publications](https://www.spiedigitallibrary.org/journals/neurophotonics/volume-8/issue-01/012101/Best-practices-for-fNIRS-publications/10.1117/1.NPh.8.1.012101.full)
- [TDDR motion correction](https://pmc.ncbi.nlm.nih.gov/articles/PMC6230489/)
- [Short-channel regression](https://pmc.ncbi.nlm.nih.gov/articles/PMC7523733/)
- [MNE-NIRS examples](https://mne.tools/stable/auto_examples/preprocessing/fnirs_artifact_removal.html)
