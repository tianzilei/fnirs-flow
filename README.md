# fnirs-flow

GUI-enabled fNIRS analysis toolbox and reproducibility framework. fnirs-flow
uses Flow graphs to orchestrate preprocessing, validation, execution, and
reproducibility workflows with an MNE-NIRS execution backend.

Run execution remains serial by default. For independent, CPU-bound multi-run
workloads, the opt-in process backend is configured with environment variables:

```text
FNIRS_PARALLEL_BACKEND=process
FNIRS_RUN_WORKERS=4
FNIRS_BLAS_THREADS=1
FNIRS_MEMORY_BUDGET_MB=4096
```

The runtime records requested and effective worker/thread budgets in execution
summary and provenance files. Single-run and resource-constrained attempts
fall back to serial before execution starts. Benchmark both modes on the target
machine with `tools/benchmark/run_execution_benchmark.py`; Windows process
startup can make small workloads slower.

**v1.3.0** | Python 3.10+

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

### Four-Step Workflow

```bash
# 1. Validate a flow configuration
python cli.py validate configs/demo_task_glm_real.json

# 2. Compile it into an executable plan
python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo

# 3. Discover a local BIDS-NIRS dataset
python cli.py discover bids-nirs-tapping --outdir outputs/demo \
  --data-root /path/to/bids-nirs-dataset

# 4. Run the analysis; requires MNE-NIRS
python cli.py run outputs/demo --outdir outputs/demo \
  --data-root /path/to/bids-nirs-dataset
```

### Start the WebUI

```bash
# Option 1: production mode (recommended)
python cli.py webui
# Production mode serves the prebuilt WebUI bundled in the wheel
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
| `discover` | Discover and register public datasets | `python cli.py discover bids-nirs-tapping --outdir outputs/demo --data-root /path/to/bids-nirs-dataset` |
| `dry-run` | Enumerate all subject/session/run combinations without execution | `python cli.py dry-run outputs/demo --outdir outputs/demo` |
| `run` | Execute analysis with MNE-NIRS | `python cli.py run outputs/demo --outdir outputs/demo --data-root /path/to/bids-nirs-dataset` |
| `export` | Export a reproducibility package | `python cli.py export outputs/demo --outdir outputs/demo` |
| `rerun` | Rerun an imported package | `python cli.py rerun outputs/imported_package` |
| `import-homer3` | Import Homer3 configuration into fnirs-flow atoms | `python cli.py import-homer3 pipeline.cfg --outdir outputs/imported` |
| `import-analyzir` | Import an AnalyzIR R script into fnirs-flow atoms | `python cli.py import-analyzir pipeline.R --outdir outputs/imported` |
| `export-homer3` | Export atoms to Homer3 configuration | `python cli.py export-homer3 atoms.json --outdir outputs/homer3` |
| `export-analyzir` | Export atoms to an AnalyzIR R script | `python cli.py export-analyzir atoms.json --outdir outputs/analyzir` |
| `webui` | Start the WebUI server | `python cli.py webui` or `python cli.py webui --dev` |
| `backends` | Show backend status and capabilities | `python cli.py backends` |
| `verify-package` | Verify `.fnirsflow.zip` package integrity | `python cli.py verify-package package.fnirsflow.zip` |
| `processed-hb-acceptance` | Write processed-Hb release-acceptance evidence | `python cli.py processed-hb-acceptance outputs/processed --output outputs/processed/acceptance.json` |

### Vendor-Processed Hb Branch

The Flow-integrated route is available for compiled
projects, package reruns, URI binding, and WebUI/API orchestration.
`vendor_processed_hb` is a data branch, not one MethodAtom. Its example flow is
composed from eight generic MethodAtoms for manifest discovery, signal reading,
event ingestion, time regularization, design compilation, first-level fitting,
contrast estimation, and derivative writing.

```bash
python cli.py validate configs/vendor_processed_hb_flow.json
python cli.py compile configs/vendor_processed_hb_flow.json --outdir outputs/processed
python cli.py discover vendor-processed-hb --outdir outputs/processed --manifest-root /path/to/frozen-inputs
python cli.py dry-run outputs/processed --outdir outputs/processed
python cli.py run outputs/processed --outdir outputs/processed
python cli.py processed-hb-acceptance outputs/processed --output outputs/processed/acceptance.json  # compatibility acceptance
```

This route accepts already converted HbO/HbR data. It does not reconstruct or
claim raw intensity, optical density, motion correction, filtering, or MBLL.
The bundled Flow preset is experimental; confirmatory use remains blocked until
all scientific thresholds are explicitly supplied and frozen. See
`docs/specs/vendor_processed_hb_analysis.md`.

`run` supports filters:

```bash
python cli.py run outputs/demo --outdir outputs/demo \
  --data-root /path/to/bids-nirs-dataset \
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

## Recommendation System (v1.3.0)

v1.3.0 completes the recommendation system's engineering layer. It provides
candidate generation, scientific eligibility, method-fit and execution-
feasibility checks, deterministic decision policy, immutable decision history,
API/package provenance, WebUI explanations, and explicit user confirmation.
Static rule-based fallback and shadow decisions are available without changing
the Flow analysis path.

The evidence system is a separate follow-up workstream. Evidence inventory,
claim review, calibration, holdout evaluation, and evidence-driven ranking are
not represented as completed scientific validation in this release. Until that
work is supplied and passes its gates, evidence-driven `best` recommendations
remain disabled; missing evidence is shown as `unverified` or `needs_review` and
does not block Flow editing, validation, compilation, or execution.

---

## Documentation

- `docs/README.md` is the public documentation index.
- `docs/specs/` contains the stable public contracts.
- `docs/specs/vendor_processed_hb_analysis.md` defines the generic processed-Hb branch.
- Compatibility aliases such as `FlowNode`, `NodeTemplate`, and `NodeLibrary` are kept only for older flows and migration paths.

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
| `Evidence Store` | Structured storage for extracted literature evidence; evidence-system development continues after v1.3.0 |
| `RecommendationDecision` | Versioned, explainable recommendation result with execution status and provenance |
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
and submission working files. See `PUBLIC_SYNC_SPEC.md` and the release
artifacts under `outputs/release/` for the published-file policy and checks.

Repository-hosted CI checks are defined in `.github/workflows/ci.yml`. Releases
are validated with those checks and the local commands in `docs/README.md`.

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
