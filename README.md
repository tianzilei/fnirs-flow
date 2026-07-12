# fnirs-flow

GUI-enabled fNIRS analysis toolbox and reproducibility framework. It uses Flow graphs to organize validation, compilation, execution, and reproducible export on top of MNE-NIRS.

**Version 1.0.2** | **446 tests** | **Python 3.10+**

## Installation

Core models and validation:

```bash
pip install -e .
```

Full analysis, API, and machine-learning dependencies:

```bash
pip install -e ".[full]"
```

Development and test dependencies:

```bash
pip install -e ".[dev]"
```

Conda users can create the supplied environment:

```bash
conda env create -f environment.yml
conda activate fnirs-flow
```

## Quick start

Validate and compile the included task-GLM example:

```bash
fnirs-flow validate configs/demo_task_glm_real.json
fnirs-flow compile configs/demo_task_glm_real.json --outdir outputs/demo
```

The repository checkout also supports `python cli.py` in place of `fnirs-flow`.

Execution requires a compatible local fNIRS dataset and the dependencies from the `full` extra:

```bash
fnirs-flow discover bids-nirs-tapping --outdir outputs/demo
fnirs-flow dry-run outputs/demo --outdir outputs/demo
fnirs-flow run outputs/demo --outdir outputs/demo
```

The `bids-nirs-tapping` registry entry expects the dataset at `Sample/BIDS-NIRS-Tapping-master`. Raw data is intentionally not included in this public repository. Users may place a compatible local copy there or adapt the registry entry for their own BIDS-NIRS dataset.

Export a completed run as a reproducibility package:

```bash
fnirs-flow export outputs/demo --outdir outputs/demo --profile reproducibility_package
```

Available export profiles are `reproducibility_package`, `submission_package`, and `reviewer_package`.

## Generative AI flow drafting

[`ai_flow_generation_guide.md`](ai_flow_generation_guide.md) provides model context, hard safety rules, input/output contracts, and task-GLM, resting-state, and machine-learning skeletons for drafting candidate FlowGraph JSON with a generative AI system.

AI-generated flows are candidates only. They must retain their AI-generation metadata, receive the required user confirmations, and pass fnirs-flow validation before execution. The guide does not permit arbitrary generated executable code.

## WebUI

Production mode builds the frontend when necessary and serves it from FastAPI:

```bash
fnirs-flow webui
```

The default address is <http://127.0.0.1:8000>.

Development mode starts the backend and frontend development servers:

```bash
fnirs-flow webui --dev
```

They can also be started separately:

```bash
python -m uvicorn fnirs_flow.api.app:app --reload
cd webui
npm ci
npm run dev
```

## CLI commands

| Command | Purpose |
|---|---|
| `validate` | Validate a Flow JSON document |
| `compile` | Compile a Flow into its plan, DAG, and manifests |
| `discover` | Discover a registered dataset and create a data manifest |
| `dry-run` | Enumerate subject/session/run units without analysis |
| `run` | Execute the compiled analysis with MNE-NIRS |
| `export` | Create a reproducibility, submission, or reviewer package |
| `rerun` | Execute an imported reproducibility package |
| `webui` | Start the API and WebUI |

Use `fnirs-flow COMMAND --help` for command-specific options.

## Repository layout

| Path | Contents |
|---|---|
| `fnirs_flow/flow/` | Flow models, schemas, snapshots, and migrations |
| `fnirs_flow/compiler/` | Flow compiler, execution DAG, manifests, and hashing |
| `fnirs_flow/execution/` | Execution engine, batch service, provenance, and artifacts |
| `fnirs_flow/adapters/` | MNE-NIRS operations, QC, ROI mapping, and Homer3 export |
| `fnirs_flow/validation/` | Graph, adapter, model, and state validation |
| `fnirs_flow/registry/` | MethodAtom templates, scenarios, evidence, risks, and presets |
| `fnirs_flow/security/` | Capability and import-readiness validation |
| `fnirs_flow/exporters/` | Package import/export and report generation |
| `fnirs_flow/api/` | FastAPI application and project persistence |
| `fnirs_flow/data/` | Dataset registry, discovery, and manifests |
| `webui/` | React and Vite frontend source |
| `configs/` | Public example Flow configurations |
| `schemas/` | Public JSON schemas |
| `docs/specs/` | Public API, package-profile, and acceptance specifications |
| `ai_flow_generation_guide.md` | Safe generative-AI FlowGraph drafting contract and examples |
| `tests/` | Self-contained Python test suite |

Generated outputs, downloaded literature, raw datasets, manuscript drafts, local reference repositories, and private working materials are excluded from this release.

## Development checks

Run the Python suite:

```bash
pytest -q
```

Build the distributable packages:

```bash
python -m build
```

Build the frontend:

```bash
cd webui
npm ci
npm run build
```

The release manifest in `PUBLIC_RELEASE_MANIFEST.json` records the expected public files, byte sizes, and SHA-256 hashes.

## Security and data handling

- Generated Flow JSON is treated as a candidate analysis plan and must pass validation before execution.
- Reproducibility packages do not include raw data by default.
- Local environment files, downloaded data, generated outputs, and common credential files are excluded by `.gitignore`.
- Imported packages pass through the security and readiness validation layer before execution.

## License

The project is licensed under the MIT License. See `LICENSE` and `THIRD_PARTY_NOTICES.md`.
