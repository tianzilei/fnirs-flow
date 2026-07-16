# MVP Task GLM Flow Acceptance Checklist

Generated: 2026-07-10

Last updated: 2026-07-11

## 1. Acceptance Checklist

### 1.1 Create a Project

- [x] Users can create a new project.
- [x] Users can select the `Task GLM` template.
- [x] The system generates an initial coarse-grained Flow.
- [x] The Flow shows these module nodes: Dataset, Study Design, QC, Preprocessing, Analysis, Reporting, and Export.
- [x] Each module node can expand into a Subflow, or expose detail through the node detail panel.

### 1.2 Select the Task GLM Template

- [x] The template automatically includes these MethodAtoms: Dataset, Study Design, QC, Preprocessing, Design Matrix, First-level GLM, Contrast, Channel Output, ROI Output, and Report/Export.
- [x] The template automatically includes evidence references.
- [x] The template automatically includes preset references for QC, preprocessing, and GLM configuration through `default_config`.

### 1.3 Link the Demo Dataset

- [x] Users can link or import the MNE-NIRS finger tapping dataset.
- [x] The system checks the dataset format, including BIDS and SNIRF compatibility.
- [x] The system checks adapter compatibility.
- [x] The Dataset node status becomes `configured`.

### 1.4 Confirm Conditions, Control Condition, and Contrasts

- [x] The system displays the condition list extracted from `study_design`.
- [x] Users can confirm or modify task conditions.
- [x] Users can confirm or modify the control condition.
- [x] Users can confirm or modify contrasts.
- [x] The Design Matrix node status becomes `configured`.

### 1.5 Confirm QC, Motion, Filter, ROI, and Export Profile Settings

- [x] The system displays QC preset parameters, and users can confirm or modify them.
- [x] The system displays motion-correction preset parameters, and users can confirm or modify them.
- [x] The system displays filter preset parameters, and users can confirm or modify them.
- [x] The system displays ROI strategy parameters, and users can confirm or modify them.
- [x] Users can choose an export profile: submission, reviewer, or reproducibility.
- [x] After all confirmations are complete, the Readiness Check status is `Ready`.

### 1.6 Save a ProjectSnapshot

- [x] Users can save a ProjectSnapshot.
- [x] The ProjectSnapshot contains Flow, compiled, data, and risk layers.
- [x] The ProjectSnapshot is immutable.
- [x] The system records `snapshot_id`, `created_at`, `version_state`, and `version_refs`.

### 1.7 Dry Run

- [x] Users can execute a dry run.
- [x] Dry run performs schema validation, graph validation, adapter validation, and readiness checks.
- [x] Dry run outputs a risk register listing all warnings and errors.
- [x] Dry run does not perform real computation.

### 1.8 Execute

- [x] Users can execute the analysis.
- [x] The system creates a ProjectSnapshot first if draft changes exist.
- [x] The system creates an ActionAttempt that references the ProjectSnapshot.
- [x] The execution engine runs in execution order: preprocessing -> analysis -> output.
- [x] Each MethodAtom execution status is recorded in the ActionAttempt.
- [x] After execution, the ActionAttempt status is `completed` or `failed`.
- [x] Artifacts generated during execution are written to the artifact manifest.

### 1.9 View Artifacts and Reports

- [x] Users can view design matrix, GLM results, and ROI result artifacts.
- [x] Users can view `run_report.md` and project reports.
- [x] Each reportlet is traceable to the source MethodAtom, source artifact, and parameter hash.
- [x] Users can view the risk register.

### 1.10 Export a Package

- [x] Users can choose an export profile.
- [x] The system generates a Flow Package (`.fnirsflow.zip`) according to the selected profile.
- [x] The package includes `plan.json`, `execution_dag.json`, `data_manifest.json`, and related manifests.
- [x] The package does not include raw data.

### 1.11 Import, Relink, and Rerun in a New Directory

- [x] Users can import a package in a new directory.
- [x] After import, the Flow is marked read-only through `import_metadata.json` and the WebUI banner.
- [x] Custom executable atoms enter the `quarantined` state. Unknown atoms are marked quarantine during registry checks.
- [x] Users can relink the data root.
- [x] Users can fork the package into a new branch by creating an editable copy.
- [x] Users can reconfirm trust. The Trust action releases quarantine for the current checksum and project.
- [x] Users can rerun readiness checks.
- [x] Users can rerun analysis after forking, because the fork removes read-only status.

## 2. Acceptance Criteria

### 2.1 Functional Acceptance

- 46/46 checklist items pass.
- No fatal error remains.
- All high-risk items have been confirmed by the user.

### 2.2 Reproducibility Acceptance

- Packages can be exported and imported.
- All parameters, evidence references, and risk records are stored in `plan.json`.
- All execution records are stored in `action_attempts.json`.
