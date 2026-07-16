# Package Profile Specification

Generated: 2026-07-10

This document summarizes the public package profile rules for fnirs-flow. It covers the default export profiles, import/export behavior, and quarantine rules for custom executable atoms.

## 1. Default Package Profiles

### 1.1 `design_review_package`

Purpose: allow collaborators or reviewers to inspect the analysis design before execution.

Default contents:

- ProjectSnapshot
- Flow files: `flow_snapshot.json`, `node_manifest.json`, `adapter_manifest.json`
- Risk files: `risk_register.json`, `risk_rules.json`
- Evidence files: `evidence_manifest.json`
- Reports: `analysis_plan.md`, `methods_rationale.md`, `validation_report.md`, `citation_report.md`

Excluded by default:

- Run ActionAttempts
- Raw data
- Large intermediate artifacts
- Deidentification layer

Reviewer mode entry point: read-only inspect mode.

### 1.2 `reproducibility_package`

Purpose: support reruns after the reviewer or collaborator relinks data on another machine.

Default contents:

- ProjectSnapshot
- Compiled manifests: `plan.json`, `execution_dag.json`, `data_manifest.json`, `reproducibility_manifest.json`
- Data metadata: `data_registry.json`, `relink_instructions.md`
- Selected ActionAttempt files: `run/artifact_manifest.json`, `run/failure_manifest.json`
- Reports: `run_report.md`

Excluded by default:

- Raw data
- Historical ActionAttempts
- Deidentification layer, unless explicitly selected

Reviewer mode entry point: inspect -> relink data -> fork -> readiness check -> rerun.

### 1.3 `submission_package`

Purpose: provide journal submission and supplementary-material artifacts.

Default contents:

- Reports: `analysis_plan.md`, `methods_rationale.md`, `validation_report.md`, `citation_report.md`, `run_report.md`
- Citation files: `CITATION.md`, `CITATION.bib`, `CITATION.html`, `CITATION.tex`
- Methods rationale
- Validation report
- Package manifest

Excluded by default:

- Complete Flow definition
- Raw data
- Large intermediate artifacts
- Source code for custom executable atoms

Reviewer mode entry point: read-only report and citation review.

## 2. Import and Export Behavior

### 2.1 Export Rules

- A package exports the current ProjectSnapshot by default.
- Users may attach selected ActionAttempts, such as run, report, export, or package attempts.
- History is excluded by default. If users explicitly select `include_history`, the package adds `history/snapshots.jsonl`.
- Custom executable atom code, dependencies, runtime manifest, dependency manifest, capability manifest, and checksums are stored under `flow/custom_nodes/`.
- RiskRule subsets, read-only imported rules, trust RiskItems, and accepted-risk fields are stored under `risk/`.

### 2.2 Import Rules

- Packages can be imported for inspection by default.
- Design-only or plan-only packages may be edited and branched.
- If a package includes run, report, export, or deidentification ActionAttempts, those attempts are immutable.
- Users may fork a package into a new Flow branch, relink data, and rerun from that branch.
- Imported project-scoped RiskRules are read-only by default. To modify or reuse them, users must copy them into local project-scoped RiskRules.

## 3. Custom Executable Atom Quarantine

### 3.1 Import State

Custom executable atoms imported from a package enter the `quarantined` state by default.

Quarantined behavior:

- Users may inspect the Flow, manifests, code summary, parameters, and risks.
- The atom cannot execute automatically.
- If source code, manifest, checksum, or dependency manifest is missing, the atom is marked `Blocked`.
- If source code exists but its checksum differs from the manifest, the atom is marked `Blocked`.

### 3.2 Trust Confirmation

After a user confirms trust:

- Trust applies only inside the current project and only for the current checksum.
- Trust does not propagate across projects, packages, versions, or checksums.
- The confirmation is recorded in `risk_register.json` as a `risk_type: trust` RiskItem.
- The confirmation record must include the affected custom atom, atom version, atom checksum, `accepted_by`, `accepted_at`, and `acceptance_note`.

### 3.3 Re-Export Rules

Re-exported packages must preserve:

- Original imported-package reference
- Local trust RiskItem
- Checksum
- Capability manifest
- Modification diff

## 4. Risk Emphasis by Profile

| Profile | Primary risk prompts |
|---|---|
| `design_review_package` | Methodological risk, parameter-choice risk, evidence applicability |
| `reproducibility_package` | Data availability, environment differences, dependency versions |
| `submission_package` | Citation completeness, report traceability, deidentification compliance |

## 5. Export Wizard Differences

| Profile | Wizard steps |
|---|---|
| `design_review_package` | Select snapshot -> confirm risk layer -> choose evidence level -> export |
| `reproducibility_package` | Select snapshot -> select ActionAttempt -> confirm data manifest -> confirm relink instructions -> export |
| `submission_package` | Select snapshot -> select reports -> confirm citations -> confirm deidentification -> export |
