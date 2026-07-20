# MVP Task GLM Flow User-Journey Acceptance Checklist

Generated: 2026-07-10
Last updated: 2026-07-11

## 1. Acceptance Checklist

### 1.1 Create a Project

- [x] The user can create a new project.
- [x] The user can select the `Task GLM` template.
- [x] The system generates the initial coarse-grained Flow.
- [x] The Flow displays these module nodes: Dataset, Study Design, QC,
  Preprocessing, Analysis, Reporting, and Export.
- [x] Each module node can expand into a Subflow. Clicking a node opens the
  detail panel.

### 1.2 Select the Task GLM Template

- [x] The template automatically includes these MethodAtoms: Dataset, Study
  Design, QC, Preprocessing, Design Matrix, First-level GLM, Contrast, Channel
  Output, ROI Output, and Report/Export.
- [x] The template automatically includes the required evidence references.
- [x] The template automatically includes the required preset references: QC
  preset, preprocessing preset, and GLM preset. `default_config` contains the
  preset values.

### 1.3 Link the Demo Dataset

- [x] The user can link or import the MNE-NIRS finger tapping dataset.
- [x] The system checks the dataset format (BIDS/SNIRF).
- [x] The system checks adapter compatibility.
- [x] The Dataset node status becomes `configured`.

### 1.4 Confirm Conditions, Control, and Contrasts

- [x] The system displays the conditions extracted from `study_design`.
- [x] The user can confirm or edit task conditions.
- [x] The user can confirm or edit the control condition.
- [x] The user can confirm or edit contrasts.
- [x] The Design Matrix node status becomes `configured`.

### 1.5 Confirm QC, Motion, Filter, ROI, and Export Profile

- [x] The system displays QC preset parameters for confirmation or editing.
- [x] The system displays motion correction preset parameters for confirmation
  or editing.
- [x] The system displays filter preset parameters for confirmation or editing.
- [x] The system displays ROI strategy parameters for confirmation or editing.
- [x] The user can select an export profile (submission, reviewer, or
  reproducibility).
- [x] After all confirmations are complete, Readiness Check status is `Ready`.

### 1.6 Save ProjectSnapshot

- [x] The user can save a ProjectSnapshot.
- [x] The ProjectSnapshot contains the flow, compiled, data, and risk layers.
- [x] The ProjectSnapshot is immutable.
- [x] The system records `snapshot_id`, `created_at`, `version_state`, and
  `version_refs`.

### 1.7 dry-run

- [x] The user can execute a dry-run.
- [x] The dry-run validates schemas, graph structure, adapters, and readiness.
- [x] The dry-run outputs a risk register that lists all warnings and errors.
- [x] The dry-run does not perform real computation.

### 1.8 execute

- [x] The user can execute the analysis.
- [x] The system creates a ProjectSnapshot first when draft changes exist. The
  snapshot is created automatically before execution.
- [x] The system creates an ActionAttempt that references the ProjectSnapshot.
- [x] The execution engine follows execution order: preprocessing -> analysis ->
  output.
- [x] Each MethodAtom execution status is recorded in the ActionAttempt.
- [x] After execution finishes, ActionAttempt status is `completed` or `failed`.
- [x] Artifacts produced during execution are written to the artifact manifest.

### 1.9 Inspect Artifacts and Reports

- [x] The user can inspect these artifacts: design matrix, GLM results, and ROI
  results.
- [x] The user can inspect these reports: `run_report.md` and `project_report`.
- [x] Each reportlet is traceable to its source MethodAtom, source artifact, and
  parameter hash.
- [x] The user can inspect the risk register.

### 1.10 Export a Package

- [x] The user can select an export profile.
- [x] The system generates a Flow Package (`.fnirsflow.zip`) according to the
  selected profile.
- [x] The package contains `plan.json`, `execution_dag.json`,
  `data_manifest.json`, and related files.
- [x] The package excludes raw data.

### 1.11 Import, Relink, and Rerun in a New Directory

- [x] The user can import the package into a new directory.
- [x] After import, the Flow is marked read-only via `import_metadata.json` and
  the WebUI banner.
- [x] Custom executable atoms enter the `quarantined` state. Registry checks
  mark unknown atoms as quarantined.
- [x] The user can relink the data root.
- [x] The user can fork to a new branch. `fork_package` creates an editable copy.
- [x] The user can confirm trust again. The Trust button removes quarantine.
- [x] The user can rerun readiness check.
- [x] The user can rerun the analysis. After fork, `read_only` is removed and
  execution works normally.

## 2. Acceptance Criteria

### 2.1 Functional Acceptance

- 46/46 checklist items passed.
- No fatal error occurred.
- All high risks were confirmed by the user.

### 2.2 Reproducibility Acceptance

- The package can be exported and imported.
- All parameters, evidence references, and risk records are present in
  `plan.json`.
- All execution records are present in `action_attempts.json`.
