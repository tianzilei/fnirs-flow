# Documentation Index

> Last updated: 2026-08-15

This page indexes the public documentation shipped with the release tree.
Private research notes, literature worktables, generated outputs, caches, and
platform metadata are excluded from the public release.

## Start Here

| Path | Use |
|---|---|
| `README.md` | Project entry point and quick start |
| `CHANGELOG.md` | Release history and verification evidence |
| `PUBLIC_SYNC_SPEC.md` | Public-tree sync policy and audit checklist |
| `PUBLIC_RELEASE.md` | Public release scope and exclusions |
| `PUBLIC_RELEASE_MANIFEST.json` | Generated release manifest |
| `ai_flow_generation_guide.md` | Prompt contract for AI-generated candidate flows |
| `docs/specs/fnirs_flow_public_api.md` | Public API and package concepts |
| `docs/specs/method_atom_parameter_ui_contract.md` | Parameter UI metadata contract |
| `docs/specs/package_profile_spec.md` | Package profile definitions |
| `docs/specs/mvp_task_glm_acceptance_checklist.md` | Task-GLM acceptance checklist |

## Public Surface

- Flow/MethodAtom models, graph validation, compiler, execution, exporters, registry, security, and data helpers
- MNE-NIRS execution path with optional Cedalion-backed adapters
- Homer3 and AnalyzIR import/export adapters
- Package export/import/rerun with portable URI relinking

Compatibility aliases such as `FlowNode`, `NodeTemplate`, and `NodeLibrary`
remain available only for older flows and migration code.

## Validation Baseline

The clean public release tree baseline is:

```text
pytest -q                                  # 1149 passed, 11 skipped
npm run test:unit                          # 22 passed
npm run build                              # passed with existing Vite chunk-size warning
```

The development tree baseline is 1158 passed and 2 skipped. Its nine additional
passes use local real-data and sample-data fixtures that are intentionally
excluded from the public release tree.

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
| `scripts/` | Public runtime, benchmark, audit, and release-sync scripts |
| `tests/` | Public test suite |
| `config/` | Tooling configuration |
| `LICENSE` / `THIRD_PARTY_NOTICES.md` / `PUBLIC_RELEASE.md` / `PUBLIC_RELEASE_MANIFEST.json` | Release metadata and notices |

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
