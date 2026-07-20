# Package Profile Business Specification

Generated: 2026-07-10

This document extracts a shorter package specification from sections 23-26 of
the business logic notes. It focuses on the three default profiles,
import/export behavior, and custom executable atom quarantine rules.

## 1. Default Package Profiles

### 1.1 design_review_package

**Purpose**: Support collaborator or reviewer inspection of the analysis plan.

**Default contents**:

- ProjectSnapshot
- Flow (`flow_snapshot.json`, `node_manifest.json`, `adapter_manifest.json`)
- Risk layer (`risk_register.json`, `risk_rules.json`)
- Evidence layer (`evidence_manifest.json`)
- Reports (`analysis_plan.md`, `methods_rationale.md`,
  `validation_report.md`, `citation_report.md`)

**Excluded**:

- Run ActionAttempt
- Raw data
- Large intermediate artifacts
- Deidentification layer

**Reviewer Mode entry**: Open directly in read-only inspect mode.

### 1.2 reproducibility_package

**Purpose**: Reproduce a run after relinking data.

**Default contents**:

- ProjectSnapshot
- Compiled manifests (`plan.json`, `execution_dag.json`,
  `data_manifest.json`, `reproducibility_manifest.json`)
- Data layer (`data_registry.json`, `relink_instructions.md`)
- Selected ActionAttempt (`run/artifact_manifest.json`,
  `run/failure_manifest.json`)
- Reports (`run_report.md`)

**Excluded**:

- Raw data
- Historical ActionAttempts
- Deidentification layer unless explicitly selected by the user

**Reviewer Mode entry**: inspect -> relink data -> fork -> readiness check ->
rerun.

### 1.3 submission_package

**Purpose**: Provide manuscript submission or supplemental materials.

**Default contents**:

- Reports (`analysis_plan.md`, `methods_rationale.md`,
  `validation_report.md`, `citation_report.md`, `run_report.md`)
- Citation files (`CITATION.md`, `CITATION.bib`, `CITATION.html`,
  `CITATION.tex`)
- Methods rationale
- Validation report
- Package manifest

**Excluded**:

- Complete Flow definition
- Raw data
- Large intermediate artifacts
- Custom executable atom source code

**Reviewer Mode entry**: Read-only report and citation inspection.

## 2. Import and Export Behavior

### 2.1 Export Rules

- Packages export the current ProjectSnapshot by default.
- Users may attach selected ActionAttempts (`run`, `report`, `export`, or
  `package`).
- History is excluded by default. When users explicitly select
  `include_history`, add `history/snapshots.jsonl`.
- Custom executable atom code, dependencies, runtime manifest, dependency
  manifest, capability manifest, and checksum are placed under
  `flow/custom_nodes/`.
- RiskRule subsets, read-only imported rules, trust RiskItems, and accepted risk
  fields are placed under `risk/`.

### 2.2 Import Rules

- Packages are importable for inspection by default.
- Packages that contain only design or plan layers may be edited and branched.
- If a package contains run, report, export, or deidentification ActionAttempts,
  those attempts are immutable.
- Imported packages may be forked into a new Flow branch, where users can relink
  data or rerun analysis.
- Imported project-scoped RiskRules are read-only by default. To modify or reuse
  them, copy them into local project-scoped RiskRules.

## 3. Custom Executable Atom Quarantine Rules

### 3.1 Import Status

Custom executable atoms imported from a package enter the `quarantined` state by
default.

Quarantined behavior:

- Users may inspect only the Flow, manifests, code summary, parameters, and
  risks.
- The atom must not execute automatically.
- If source code, manifest, checksum, or dependency manifest is missing from the
  package, the atom is `Blocked`.
- If source code exists but the checksum does not match the manifest, the atom
  is `Blocked`.

### 3.2 Trust Confirmation Flow

After the user confirms trust:

- Trust applies only inside the current project and for the current checksum.
- Trust does not propagate across projects, packages, versions, or checksums.
- The confirmation is written as a `risk_type: trust` RiskItem in
  `risk_register.json`.
- The confirmation record must include at least the affected custom atom, atom
  version, atom checksum, `accepted_by`, `accepted_at`, and `acceptance_note`.

### 3.3 Re-Export Rules

Re-exported packages must preserve:

- Original `imported_package` reference
- Local confirmation RiskItem
- Checksum
- Capability manifest
- Modification diff

## 4. Risk Prompt Differences

| Profile | Risk Prompt Focus |
|---|---|
| design_review_package | Methodological risk, parameter-selection risk, and evidence applicability |
| reproducibility_package | Data availability, environment differences, and dependency versions |
| submission_package | Citation completeness, report traceability, and deidentification compliance |

## 5. Export Wizard Differences

| Profile | Export Wizard Steps |
|---|---|
| design_review_package | Select snapshot -> confirm risk layer -> select evidence level -> export |
| reproducibility_package | Select snapshot -> select ActionAttempt -> confirm data manifest -> confirm relink instructions -> export |
| submission_package | Select snapshot -> select reports -> confirm citations -> confirm deidentification -> export |
