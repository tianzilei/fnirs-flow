# Documentation Index

> Last updated: 2026-07-20

This public repository contains the code-oriented release tree for fnirs-flow.
Private manuscript drafts, literature extraction worktables, sample datasets,
generated outputs, reference repositories, local caches, and platform metadata
are intentionally excluded.

## Public Docs

| Path | Purpose |
|---|---|
| `docs/README.md` | Public documentation index |
| `docs/specs/fnirs_flow_public_api.md` | Public Python/API surface and package concepts |
| `docs/specs/package_profile_spec.md` | Submission, reviewer, and reproducibility package profiles |
| `docs/specs/mvp_task_glm_acceptance_checklist.md` | Task-GLM MVP acceptance checklist |
| `PUBLIC_RELEASE.md` | Release-tree scope and exclusion policy |
| `PUBLIC_RELEASE_MANIFEST.json` | Generated manifest with copied paths, byte counts, and SHA-256 hashes |
| `PUBLIC_SYNC_SPEC.md` | Public sync process, audit gate, and required Markdown update checklist |
| `ai_flow_generation_guide.md` | Prompt/context contract for AI-generated candidate FlowGraph JSON |
| `CHANGELOG.md` | Release notes and verification history |

## Current Capabilities

### Core

- Flow/MethodAtom models, graph validation, compiler, risk register, and reporting checklist
- Backend abstraction through BackendProtocol, BackendRegistry, and BackendBinding
- MNE-NIRS execution path and optional Cedalion adapter capabilities
- Homer3 and AnalyzIR import/export adapters
- Security model for trust levels, capability manifests, quarantine, and readiness checks

### Execution

- Task-GLM fNIRS execution chain: read_run -> optical_density -> QC -> motion_correction -> filtering -> MBLL -> design_matrix -> GLM -> contrast -> channel_output -> roi_output
- BIDS events TSV parsing for design matrix construction
- Structured artifact, provenance, failure, QC, channel, ROI, and group-level outputs
- Package export/import/rerun with portable URI relinking

### WebUI

- Project workspace, Flow builder, MethodAtom library, data import, validation, compile summary, run monitor, results browser, import/export package views, and diagnostics
- Checklist guidance for Task GLM, resting-state connectivity, group analysis, and ML classification workflows
- Checklist-to-Atom Library recommendations with priority actions, focus routing, and missing-input previews
- Results Workspace tabs for artifacts, QC, channel, ROI, and group-level SVG/CSV/JSON outputs
- Import quarantine handling and export profile selection for reproducibility, submission, and reviewer packages

## Validation Baseline

The latest release convergence recorded in `CHANGELOG.md` reports:

```text
pytest -q                                  # 1126 passed, 1 skipped
npm run test:unit                          # 9 passed
npm run build -- --mode development        # passed with existing Vite chunk-size warning
npx playwright test e2e/workflows.spec.ts  # 6 passed
```

For a public-tree lint pass, run:

```text
ruff check cli.py fnirs_flow tests scripts
```

## Public Release Contents

| Path | Contents |
|---|---|
| `fnirs_flow/` | Python package, API, adapters, compiler, execution, exporters, registry, security, validation, and data helpers |
| `webui/` | React + Vite WebUI source, package metadata, and Playwright specs |
| `configs/` | Demo and evidence-backed FlowGraph configurations |
| `schemas/` | Public JSON schemas |
| `scripts/` | Public runtime, benchmark, audit, ds007738, and release-sync scripts |
| `tests/` | Public test suite |
| `config/` | Tooling configuration |

## Commands

```bash
python cli.py validate configs/demo_task_glm_real.json
python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo
python cli.py discover bids-nirs-tapping --outdir outputs/demo
python cli.py dry-run outputs/demo --outdir outputs/demo
python cli.py run outputs/demo --outdir outputs/demo
python cli.py export outputs/demo --outdir outputs/demo --profile reproducibility_package
python cli.py verify-package outputs/demo/package.fnirsflow.zip
python cli.py webui
python cli.py backends
```
