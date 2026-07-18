# Package Profile Business Specification

Generated: 2026-07-10

This document extracts a shorter package specification from sections 23-26 of the business logic notes. It focuses on the three default profiles, import/export behavior, and custom executable atom quarantine rules.

## 1. Three Default Package Profiles

### 1.1 design_review_package

**Purpose**: allow collaborators or reviewers to inspect the analysis plan.

**Default contents**:

- ProjectSnapshot
- Flow (`flow_snapshot.json`, `node_manifest.json`, `adapter_manifest.json`)
- risk (`risk_register.json`, `risk_rules.json`)
- evidence (`evidence_manifest.json`)
- reports (`analysis_plan.md`, `methods_rationale.md`, `validation_report.md`, `citation_report.md`)

**Excluded**:

- run ActionAttempt
- raw data
- large intermediate artifacts
- deidentification layer

**Reviewer Mode entry point**: enter read-only inspect mode directly.

### 1.2 reproducibility_package

**Purpose**: reproduce a run after relinking data.

**Default contents**:

- ProjectSnapshot
- compiled manifests (`plan.json`, `execution_dag.json`, `data_manifest.json`, `reproducibility_manifest.json`)
- data (`data_registry.json`, `relink_instructions.md`)
- selected ActionAttempt (`run/artifact_manifest.json`, `run/failure_manifest.json`)
- reports (`run_report.md`)

**Excluded**:

- raw data
- historical ActionAttempts
- deidentification layer, unless explicitly selected by the user

**Reviewer Mode entry point**: inspect -> relink data -> fork -> readiness check -> rerun.

### 1.3 submission_package

**Purpose**: provide submission or supplementary materials.

**Default contents**:

- reports (`analysis_plan.md`, `methods_rationale.md`, `validation_report.md`, `citation_report.md`, `run_report.md`)
- citation (`CITATION.md`, `CITATION.bib`, `CITATION.html`, `CITATION.tex`)
- methods rationale
- validation report
- package manifest

**Excluded**:

- complete Flow definition
- raw data
- large intermediate artifacts
- custom executable atom source code

**Reviewer Mode entry point**: read-only report and citation inspection.

## 2. Import and Export Behavior

### 2.1 Export Rules

- By default, a package exports the current ProjectSnapshot.
- The user can optionally attach ActionAttempts for run, report, export, or package actions.
- History is not packaged by default; when the user explicitly selects `include_history`, `history/snapshots.jsonl` is added.
- Custom executable atom code, dependencies, runtime manifest, dependency manifest, capability manifest, and checksum are placed under `flow/custom_nodes/`.
- RiskRule subsets, read-only imported rules, trust RiskItems, and accepted risk fields are placed under `risk/`.

### 2.2 Import Rules

- By default, a package can be imported for inspection.
- If the package contains only the design/plan layer, it can be edited and branched.
- If the package contains run, reports, export, or deidentification ActionAttempts, those attempts are immutable.
- The package can be forked into a new Flow branch, where data can be relinked or the analysis can be rerun.
- Imported project-scoped RiskRules are read-only by default. To modify or continue reusing one, copy it into a local project-scoped RiskRule.

## 3. Custom Executable Atom Quarantine Rules

### 3.1 Import-Time State

Custom executable atoms in an imported package enter the `quarantined` state by default.

Quarantined behavior:

- The user can only inspect the Flow, manifest, code summary, parameters, and risks.
- The atom cannot execute automatically.
- If the package is missing source code, manifest, checksum, or dependency manifest, the atom is `Blocked`.
- If source code exists but the checksum does not match the manifest, the atom is `Blocked`.

### 3.2 Trust Confirmation Flow

After the user confirms trust:

- Trust applies only within the current project and current checksum.
- Trust does not propagate across projects, packages, versions, or checksums.
- The confirmation record is written to `risk_register.json` as a RiskItem with `risk_type: trust`.
- The confirmation record must contain at least the affected custom atom, atom version, atom checksum, `accepted_by`, `accepted_at`, and `acceptance_note`.

### 3.3 Re-Export Rules

When re-exporting, the package must preserve:

- the original `imported_package` reference
- local confirmation RiskItems
- checksum
- capability manifest
- modification diff

## 4. Risk Prompt Differences

| Profile | Risk prompt focus |
|---|---|
| design_review_package | Methodology risk, parameter-selection risk, and evidence applicability |
| reproducibility_package | Data availability, environment differences, and dependency versions |
| submission_package | Citation completeness, report traceability, and deidentification compliance |

## 5. Export Wizard Differences

| Profile | Export wizard steps |
|---|---|
| design_review_package | Select snapshot -> confirm risk layer -> select evidence level -> export |
| reproducibility_package | Select snapshot -> select ActionAttempt -> confirm data manifest -> confirm relink instructions -> export |
| submission_package | Select snapshot -> select reports -> confirm citation -> confirm deidentification -> export |
