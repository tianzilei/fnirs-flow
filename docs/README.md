# Documentation Index

> Last updated: 2026-09-02

This page indexes the public documentation shipped with the release tree.
Private research notes, literature worktables, generated outputs, caches, and
platform metadata are excluded from the public release.

## Start Here

| Path | Use |
|---|---|
| `README.md` | Project entry point and quick start |
| `CHANGELOG.md` | Release history and verification evidence |
| `PUBLIC_SYNC_SPEC.md` | Public-tree sync policy and audit checklist |
| `PUBLIC_SYNC_SPEC.md` | Public release scope, sync policy, and exclusions |
| `ai_flow_generation_guide.md` | Prompt contract for AI-generated candidate flows |
| `docs/specs/fnirs_flow_public_api.md` | Public API and package concepts |
| `docs/specs/method_atom_parameter_ui_contract.md` | Parameter UI metadata contract |
| `docs/specs/package_profile_spec.md` | Package profile definitions |
| `docs/specs/mvp_task_glm_acceptance_checklist.md` | Task-GLM acceptance checklist |
| `docs/specs/vendor_processed_hb_analysis.md` | Generic vendor-processed Hb branch and MethodAtom contract |

## Public Surface

- Flow/MethodAtom models, graph validation, compiler, execution, exporters, registry, security, and data helpers
- MNE-NIRS execution path with optional Cedalion-backed adapters
- Homer3 and AnalyzIR import/export adapters
- Package export/import/rerun with portable URI relinking
- Generic vendor-processed Hb discovery, design, first-level, contrast, derivative, and acceptance workflow
- Versioned recommendation decisions with backend policy, persistence,
  provenance, WebUI explanations, and explicit user confirmation

The v1.3.0 recommendation system is complete for static, shadow, and
rule-based fallback operation. The evidence system remains a separate follow-up
workstream: incomplete evidence or missing calibration/holdout data is reported
as `unverified`/`needs_review`, does not produce an evidence-driven `best`, and
does not block Flow analysis.

Compatibility aliases such as `FlowNode`, `NodeTemplate`, and `NodeLibrary`
remain available only for older flows and migration code.

## Validation Baseline

The public tree is validated with the synchronization tests and the release
commands listed below. Detailed development status reports are intentionally
kept outside this code-oriented release tree.

Repository CI checks are defined in `.github/workflows/ci.yml`; maintainers
also run the local commands below before creating a release.

The 2026-08-31 release audit passed the clean public Python suite with 1,429
tests and 13 environment/real-data skips. The final development suite passed
1,449 tests with 3 skips. All 26 WebUI unit tests, Ruff, core and MNE mypy,
the production WebUI build, package and license checks, and Python/npm
dependency audits passed.
The Playwright Chromium/Firefox/WebKit matrix passed 36 tests with one opt-in
real-data scenario skipped. Public-sync dry-run, English-only, generic-naming,
and forbidden-path gates also passed.

The primary local reproduction commands are:

```text
python -m pytest --tb=short -q -p no:cacheprovider
python -m pytest tests/test_processed_hb_flow_gate.py tests/test_processed_hb_design_contract.py -q
python -m ruff check cli.py fnirs_flow tests scripts tools
npm --prefix webui run test:unit
npm --prefix webui run build
```

## Public Release Contents

| Path | Contents |
|---|---|
| `fnirs_flow/` | Python package, API, adapters, compiler, execution, exporters, registry, security, validation, and data helpers |
| `webui/` | React + Vite WebUI source, package metadata, and Playwright specs |
| `configs/` | Demo and evidence-backed FlowGraph configurations |
| `schemas/` | Public JSON schemas |
| `scripts/` | Public runtime, benchmark, audit, and release-sync scripts |
| `tests/` | Public test suite |
| `config/` | Tooling configuration |
| `LICENSE` / `THIRD_PARTY_NOTICES.md` / `PUBLIC_SYNC_SPEC.md` | Release metadata, notices, and synchronization policy |

## Commands

```bash
python cli.py validate configs/demo_task_glm_real.json
python cli.py compile configs/demo_task_glm_real.json --outdir outputs/demo
python cli.py discover bids-nirs-tapping --outdir outputs/demo --data-root /path/to/bids-nirs-dataset
python cli.py dry-run outputs/demo --outdir outputs/demo
python cli.py run outputs/demo --outdir outputs/demo --data-root /path/to/bids-nirs-dataset
python cli.py export outputs/demo --outdir outputs/demo --profile reproducibility_package
python cli.py verify-package outputs/demo/package.fnirsflow.zip
python cli.py webui
python cli.py backends
python cli.py validate configs/vendor_processed_hb_flow.json
python cli.py processed-hb-acceptance outputs/processed --output outputs/processed/acceptance.json  # compatibility route
```
