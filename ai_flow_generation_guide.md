# AI Flow Generation Guide

Purpose: give a generative AI system enough project context to draft a valid fnirs-flow analysis chain. The AI must output a candidate FlowGraph, not executable code.

Use this document as the model context when asking an AI to generate an fNIRS analysis flow.

## Hard Rules

- Output a candidate `flow.json` only. Do not output Python, shell commands, notebook code, or arbitrary executable nodes.
- Use `schema_version: "0.2.0"`.
- Prefer `flow_atoms`; for current fnirs-flow compatibility, duplicate the same array to `nodes` before validation/import.
- Use only these categories: `data`, `design`, `preprocessing`, `analysis`, `output`, `validation`, `export`.
- Use only builtin or evidence-derived atoms unless the user explicitly asks for a custom atom.
- If a custom executable atom is requested, set `execution_trust_level: "imported_custom"` and `security_status: "quarantined"`.
- Do not mark high-impact parameters as final. Put them in `metadata.ai_generation.requires_user_confirmation`.
- Do not invent literature claims. Use `evidence_refs` only when the caller provides concrete evidence IDs.
- Do not include raw data, PHI, private paths, access tokens, or local absolute paths.
- The generated flow must still pass fnirs-flow validation before execution.

## Expected Input

Ask the caller for these fields, or make conservative assumptions and list them in `metadata.ai_generation.assumptions`:

```json
{
  "study_goal": "task GLM | resting-state connectivity | ML validation | other",
  "data_format": "SNIRF | NIRS-BIDS | NIRx | vendor-specific | unknown",
  "dataset_id": "optional public dataset or project dataset ID",
  "conditions": ["condition names"],
  "contrasts": ["condition_a > condition_b"],
  "outputs": ["channel-level", "ROI-level", "report", "package"],
  "preferences": {
    "motion_correction": "tddr | spline | wavelet | unknown",
    "filter_band_hz": {"low": 0.01, "high": 0.2},
    "short_channel_regression": "yes | no | unknown",
    "roi_mapping": "provided | template | unknown",
    "ml_split": "subject-level | family/dyad-level | unknown"
  }
}
```

## Output Shape

Return JSON with this top-level structure:

```json
{
  "schema_version": "0.2.0",
  "flow_id": "ai-draft-task-glm-001",
  "name": "AI Draft Task GLM Flow",
  "description": "Candidate flow generated from user-provided study description; requires validation and user confirmation.",
  "flow_atoms": [],
  "nodes": [],
  "edges": [],
  "adapter_registry": [],
  "metadata": {
    "ai_generation": {
      "generated_by": "generative_ai",
      "model": "unspecified",
      "created_at": "YYYY-MM-DD",
      "input_summary": "",
      "assumptions": [],
      "requires_user_confirmation": [],
      "not_used_for_execution": true
    }
  }
}
```

For direct validation/import in the current codebase, copy the final `flow_atoms` array into `nodes`. The empty `nodes` array above is only a compact placeholder for the shape example.

Each atom should use this minimal shape:

```json
{
  "id": "optical_density",
  "type": "optical_density",
  "atom_type": "optical_density",
  "operation": "optical_density",
  "category": "preprocessing",
  "origin": "builtin",
  "position": {"x": 400, "y": 0},
  "config": {},
  "ports": [
    {"name": "raw_data", "direction": "in", "schema": "RawData", "required": true},
    {"name": "od_data", "direction": "out", "schema": "OpticalDensityData", "required": true}
  ],
  "readiness_status": "needs_attention",
  "execution_status": "not_run",
  "security_status": "trusted",
  "execution_trust_level": "builtin_managed",
  "evidence_refs": []
}
```

Each edge should use this shape:

```json
{
  "id": "e-source-target",
  "source": "source_atom_id",
  "target": "target_atom_id",
  "source_handle": "source_output_port",
  "target_handle": "target_input_port"
}
```

## Common Port Schemas

Use these port schema names when possible:

| Schema | Meaning |
|---|---|
| `DataManifest` | Discovered dataset manifest |
| `RawData` | Raw fNIRS data loaded by adapter |
| `DesignSpec` | Conditions, events, contrasts |
| `OpticalDensityData` | Optical density data |
| `QCReport` | QC metrics and channel decisions |
| `HaemoglobinData` | HbO/HbR concentration data |
| `DesignMatrix` | First-level GLM design matrix |
| `GLMResults` | First-level model output |
| `ContrastResults` | Contrast estimates |
| `ConnectivityMatrix` | Resting/hyperscanning connectivity output |
| `MLFeatures` | Machine-learning features |
| `MLValidationReport` | ML split/leakage validation |
| `CSVFile` | Exported table |
| `Report` | Report or checklist |
| `FlowPackage` | Export package |

## Task GLM Skeleton

Use this chain for task-based HbO/HbR GLM analysis:

```text
dataset_discovery
-> study_design
-> optical_density
-> qc_metrics
-> motion_correction
-> filtering
-> beer_lambert_law
-> design_matrix
-> first_level_glm
-> contrast
-> channel_output
-> roi_output
-> reporting_checklist
-> package_export
```

Required confirmations:

- conditions and control condition
- contrasts
- motion correction method
- filter band
- ppf value
- short-channel/systemic regression decision
- ROI mapping
- package profile

## Resting-State Skeleton

Use this chain for resting-state connectivity:

```text
dataset_discovery
-> optical_density
-> qc_metrics
-> motion_correction
-> filtering
-> beer_lambert_law
-> connectivity_analysis
-> channel_output or roi_output
-> reporting_checklist
-> package_export
```

Required confirmations:

- frequency band
- connectivity metric
- ROI/channel aggregation
- motion and systemic physiology handling
- multiple-comparison or graph-metric reporting plan

## ML Validation Skeleton

Use this chain for machine-learning studies:

```text
dataset_discovery
-> study_design
-> optical_density
-> qc_metrics
-> motion_correction
-> filtering
-> beer_lambert_law
-> feature_extraction
-> ml_split_validation
-> ml_model
-> ml_evaluation
-> reporting_checklist
-> package_export
```

Required confirmations:

- subject-level or family/dyad-level split
- no random trial/window leakage
- feature extraction timing relative to split
- cross-validation grouping
- held-out test policy
- fairness/inclusion audit fields

## Minimal Task GLM Example

```json
{
  "schema_version": "0.2.0",
  "flow_id": "ai-draft-task-glm-001",
  "name": "AI Draft Task GLM Flow",
  "description": "Candidate task GLM flow requiring validation and user confirmation.",
  "flow_atoms": [
    {
      "id": "dataset_discovery",
      "type": "dataset_discovery",
      "atom_type": "dataset_discovery",
      "operation": "dataset_discovery",
      "category": "data",
      "origin": "builtin",
      "position": {"x": 0, "y": 0},
      "config": {"dataset_id": "mne-fnirs-motor", "source_kind": "mne_nirs_dataset"},
      "ports": [{"name": "data_manifest", "direction": "out", "schema": "DataManifest", "required": true}],
      "readiness_status": "needs_attention",
      "execution_status": "not_run",
      "security_status": "trusted",
      "execution_trust_level": "builtin_managed"
    },
    {
      "id": "study_design",
      "type": "study_design",
      "atom_type": "study_design",
      "operation": "study_design",
      "category": "design",
      "origin": "builtin",
      "position": {"x": 200, "y": 0},
      "config": {"design_type": "block", "conditions": ["tapping", "rest"], "contrasts": ["tapping > rest"]},
      "ports": [{"name": "design_spec", "direction": "out", "schema": "DesignSpec", "required": true}],
      "readiness_status": "needs_attention",
      "execution_status": "not_run",
      "security_status": "trusted",
      "execution_trust_level": "builtin_managed"
    },
    {
      "id": "optical_density",
      "type": "optical_density",
      "atom_type": "optical_density",
      "operation": "optical_density",
      "category": "preprocessing",
      "origin": "builtin",
      "position": {"x": 400, "y": 0},
      "config": {},
      "ports": [
        {"name": "raw_data", "direction": "in", "schema": "RawData", "required": true},
        {"name": "od_data", "direction": "out", "schema": "OpticalDensityData", "required": true}
      ],
      "readiness_status": "needs_attention",
      "execution_status": "not_run",
      "security_status": "trusted",
      "execution_trust_level": "builtin_managed"
    },
    {
      "id": "qc_metrics",
      "type": "qc_metrics",
      "atom_type": "qc_metrics",
      "operation": "qc_metrics",
      "category": "preprocessing",
      "origin": "builtin",
      "position": {"x": 600, "y": 0},
      "config": {"preset": "conservative_qc"},
      "ports": [
        {"name": "raw_data", "direction": "in", "schema": "RawData", "required": true},
        {"name": "qc_report", "direction": "out", "schema": "QCReport", "required": true}
      ],
      "readiness_status": "needs_attention",
      "execution_status": "not_run",
      "security_status": "trusted",
      "execution_trust_level": "builtin_managed"
    },
    {
      "id": "beer_lambert_law",
      "type": "beer_lambert_law",
      "atom_type": "beer_lambert_law",
      "operation": "beer_lambert_law",
      "category": "preprocessing",
      "origin": "builtin",
      "position": {"x": 800, "y": 0},
      "config": {"ppf": 6.0},
      "ports": [
        {"name": "od_data", "direction": "in", "schema": "OpticalDensityData", "required": true},
        {"name": "haemoglobin", "direction": "out", "schema": "HaemoglobinData", "required": true}
      ],
      "readiness_status": "needs_attention",
      "execution_status": "not_run",
      "security_status": "trusted",
      "execution_trust_level": "builtin_managed"
    },
    {
      "id": "design_matrix",
      "type": "design_matrix",
      "atom_type": "design_matrix",
      "operation": "design_matrix",
      "category": "analysis",
      "origin": "builtin",
      "position": {"x": 1000, "y": 0},
      "config": {"hrf_model": "canonical"},
      "ports": [
        {"name": "haemoglobin", "direction": "in", "schema": "HaemoglobinData", "required": true},
        {"name": "design_spec", "direction": "in", "schema": "DesignSpec", "required": true},
        {"name": "design_matrix", "direction": "out", "schema": "DesignMatrix", "required": true}
      ],
      "readiness_status": "needs_attention",
      "execution_status": "not_run",
      "security_status": "trusted",
      "execution_trust_level": "builtin_managed"
    },
    {
      "id": "first_level_glm",
      "type": "first_level_glm",
      "atom_type": "first_level_glm",
      "operation": "first_level_glm",
      "category": "analysis",
      "origin": "builtin",
      "position": {"x": 1200, "y": 0},
      "config": {},
      "ports": [
        {"name": "haemoglobin", "direction": "in", "schema": "HaemoglobinData", "required": true},
        {"name": "design_matrix", "direction": "in", "schema": "DesignMatrix", "required": true},
        {"name": "glm_results", "direction": "out", "schema": "GLMResults", "required": true}
      ],
      "readiness_status": "needs_attention",
      "execution_status": "not_run",
      "security_status": "trusted",
      "execution_trust_level": "builtin_managed"
    }
  ],
  "nodes": [],
  "edges": [
    {"id": "e-data-od", "source": "dataset_discovery", "target": "optical_density", "source_handle": "data_manifest", "target_handle": "raw_data"},
    {"id": "e-data-qc", "source": "dataset_discovery", "target": "qc_metrics", "source_handle": "data_manifest", "target_handle": "raw_data"},
    {"id": "e-od-mbll", "source": "optical_density", "target": "beer_lambert_law", "source_handle": "od_data", "target_handle": "od_data"},
    {"id": "e-mbll-design", "source": "beer_lambert_law", "target": "design_matrix", "source_handle": "haemoglobin", "target_handle": "haemoglobin"},
    {"id": "e-study-design", "source": "study_design", "target": "design_matrix", "source_handle": "design_spec", "target_handle": "design_spec"},
    {"id": "e-design-glm", "source": "design_matrix", "target": "first_level_glm", "source_handle": "design_matrix", "target_handle": "design_matrix"},
    {"id": "e-mbll-glm", "source": "beer_lambert_law", "target": "first_level_glm", "source_handle": "haemoglobin", "target_handle": "haemoglobin"}
  ],
  "adapter_registry": [
    {"adapter_id": "mne-data-to-raw", "name": "MNE Dataset to Raw", "source_type": "DataManifest", "target_type": "RawData", "transform": "Read SNIRF/NIRS-BIDS files through MNE-NIRS"}
  ],
  "metadata": {
    "ai_generation": {
      "generated_by": "generative_ai",
      "model": "unspecified",
      "created_at": "2026-07-11",
      "input_summary": "Task GLM draft using MNE-NIRS motor dataset.",
      "assumptions": ["Conditions are tapping and rest.", "Contrast is tapping > rest."],
      "requires_user_confirmation": ["conditions", "contrasts", "ppf", "motion correction", "filter band", "ROI mapping"],
      "not_used_for_execution": true
    }
  }
}
```

Note: the example intentionally stops before execution-ready completeness. A final draft should add motion correction, filtering, contrast, channel/ROI output, reporting, and package export atoms, then run fnirs-flow validation.

For a final importable draft, duplicate the `flow_atoms` array into `nodes` before handing the JSON to fnirs-flow.

## Final Self-Check Before Returning JSON

- Does every edge point to existing atoms?
- Does every edge handle match a declared port name?
- Are high-impact parameters listed for user confirmation?
- Are all executable custom atoms quarantined or avoided?
- Is `metadata.ai_generation.not_used_for_execution` set to `true`?
- Is the output valid JSON without Markdown fences when the caller asks for machine-readable output?
