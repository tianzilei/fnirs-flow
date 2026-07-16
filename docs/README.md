# Documentation Index

> Last updated: 2026-07-16

This directory contains the public, code-oriented documentation shipped with the fnirs-flow release tree.

## Validation Baseline

```text
python -m ruff check cli.py fnirs_flow tests scripts  # 0 errors
python -m pytest                                      # source: 1060 passed, 4 skipped; public: 1059 passed, 5 skipped
npm audit (webui/)                                    # 0 vulnerabilities
npm run build (webui/)                                # success
```

## Public Documents

| Document | Purpose |
|---|---|
| [Task GLM WebUI Tutorial](tutorials/task_glm_webui_tutorial.md) | Screenshot-based tutorial for the WebUI analysis workflow |
| [Public API Contract](specs/fnirs_flow_public_api.md) | Stable public model, package, artifact, error-code, and CLI surfaces |
| [Package Profile Specification](specs/package_profile_spec.md) | Export/import profile rules, quarantine behavior, and reviewer workflows |
| [MVP Task GLM Acceptance Checklist](specs/mvp_task_glm_acceptance_checklist.md) | End-to-end acceptance criteria for the Task GLM user path |
| [AI Flow Generation Guide](../ai_flow_generation_guide.md) | Prompt context and safety rules for AI-generated Flow drafts |
| [Third-Party Notices](../THIRD_PARTY_NOTICES.md) | Public release dependency and reference boundary notes |
| [Changelog](../CHANGELOG.md) | Release history |

## Current Capabilities

### Core Framework

- Flow and MethodAtom models
- Validation rules for graph structure, adapters, state, and typed errors
- Flow compiler, risk register, and reporting checklist
- Backend abstraction through `BackendProtocol`, `BackendRegistry`, and `BackendBinding`
- MNE-NIRS execution backend and optional Cedalion backend
- Evidence-aware MethodAtom registry and preset support

### Execution Engine

- Task GLM execution chain: `read_run -> optical_density -> QC -> motion_correction -> filtering -> MBLL -> design_matrix -> GLM -> contrast -> channel_output -> roi_output`
- BIDS events TSV parsing for design matrix construction
- Structured artifact, provenance, and failure manifests
- Batch execution at subject/session/run granularity

### CLI

```text
python cli.py validate        <flow.json>
python cli.py compile         <flow.json> --outdir <dir>
python cli.py discover        <dataset_id> --outdir <dir>
python cli.py dry-run         <dir>
python cli.py run             <dir>
python cli.py export          <dir> --profile <submission|reviewer|reproducibility>
python cli.py verify-package  <package.zip>
python cli.py backends
```

### WebUI

- Project management and Flow Canvas
- Data import and dataset discovery
- Validation dashboard and compile summary
- Run monitor with Dry Run and Execute controls
- Results Workspace for artifacts, QC, channel, ROI, and group outputs
- Import Package workflow with quarantine management and fork support
- Export Profile Selector for reproducibility, submission, and reviewer packages
- DAG layer preview and fatal-risk execution gating

### Package Model

- Editable WebUI projects are saved as `.fnirsflow` files.
- Exported `.fnirsflow.zip` packages are read-only exchange artifacts.
- Package profiles support submission, reviewer, and reproducibility workflows.
- Export and import preserve `plan.json`, `execution_dag.json`, `data_manifest.json`, manifests, reports, and relink instructions according to profile.
- Package verification checks profile, schema, checksum, backend manifest, artifacts, relink metadata, and version boundaries.

### CI/CD

- `.github/workflows/ci.yml`: Python 3.11 to 3.13 matrix, Ruff linting, pytest, and WebUI build
- `environment.yml`: conda environment definition

## Deferred Work

- Semantic merge support for FlowVCS design histories
- Real execution paths for resting-state, hyperscanning, and ML scenarios
- Full CLI/WebUI productization of the generative AI draft entry point
