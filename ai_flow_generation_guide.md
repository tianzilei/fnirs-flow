# AI Flow Generation Guide

Updated: 2026-07-15

Release: fnirs-flow v1.2.0

This guide describes the current public AI draft contract in fnirs-flow. The
feature is a review-first draft workflow: an AI or template generator may create
a candidate FlowGraph, but the candidate is not the executable project flow
until it is validated and explicitly confirmed by a human reviewer.

The public implementation in v1.2.0 includes:

- a template-based draft generator in `fnirs_flow/ai/draft_generator.py`
- a CLI entry point: `python cli.py generate-flow-draft`
- standalone draft generation endpoint: `POST /api/ai/draft-flow`
- project draft lifecycle endpoints under `/api/projects/{project_id}/ai/`
- WebUI review, validation, confirmation, and discard controls

The current FlowGraph schema remains `schema_version: "0.2.0"`.

## Contract

AI draft generation must produce candidate FlowGraph JSON only. It must not
produce Python, shell commands, notebooks, hidden side effects, or executable
custom code.

A draft is expected to carry this metadata block:

```json
{
  "metadata": {
    "author": "ai-draft",
    "tags": ["task", "ai-generated"],
    "ai_generation": {
      "generated_by": "generative_ai",
      "model": "template_based",
      "created_at": "2026-07-15T00:00:00+00:00",
      "input_summary": "Scenario: task, format: snirf",
      "assumptions": [],
      "requires_user_confirmation": [],
      "confirmed_parameters": [],
      "not_used_for_execution": true
    }
  }
}
```

`not_used_for_execution` starts as `true`. Review-aware clients should set it to
`false` only when the reviewer has confirmed every item in
`requires_user_confirmation` and the draft is applied to the current project
flow.

## Hard Rules

- Use `schema_version: "0.2.0"`.
- Output FlowGraph JSON, not executable code.
- Use `nodes` as the importable atom list. If a producer also emits
  `flow_atoms`, keep it synchronized with `nodes`.
- Use only known categories: `data`, `design`, `preprocessing`, `analysis`,
  `output`, `validation`, `export`.
- Prefer built-in atoms from the public registry.
- If a custom executable atom is unavoidable, mark it as untrusted:
  `execution_trust_level: "imported_custom"` and
  `security_status: "quarantined"`.
- Put high-impact choices in
  `metadata.ai_generation.requires_user_confirmation`.
- Do not invent literature claims. Use `evidence_refs` only when the caller
  provides concrete evidence IDs.
- Do not include PHI, raw data, private paths, access tokens, host-specific
  absolute paths, or unpublished local file references.
- Validate the draft before confirmation.

## Supported Public Entry Points

### CLI

```bash
python cli.py generate-flow-draft task \
  --name "Motor Task GLM" \
  --format snirf \
  --conditions "Control,Tapping/Left,Tapping/Right" \
  --model template_based \
  --output draft.flow.json
```

The CLI writes a candidate FlowGraph. It does not overwrite an existing project
flow.

### Standalone API

```http
POST /api/ai/draft-flow
```

Example body:

```json
{
  "scenario": "task",
  "study_name": "Motor Task GLM",
  "data_format": "snirf",
  "conditions": ["Control", "Tapping/Left", "Tapping/Right"],
  "model": "template_based",
  "assumptions": ["Block design"],
  "user_confirmations": ["short_channel_regression: confirm whether to include"]
}
```

This endpoint returns a candidate draft and does not attach it to a project.

### Project Draft Lifecycle

```http
POST   /api/projects/{project_id}/ai/draft-flow
GET    /api/projects/{project_id}/ai/draft
POST   /api/projects/{project_id}/ai/validate-draft
POST   /api/projects/{project_id}/ai/confirm-draft
DELETE /api/projects/{project_id}/ai/draft
```

Project draft behavior:

- `draft-flow` saves the candidate as `pending_draft`.
- The current project flow is not overwritten while a draft is pending.
- `validate-draft` runs validation against the pending draft without applying it.
- `confirm-draft` applies the pending draft as the current flow.
- `DELETE /draft` discards the pending draft without changing the current flow.

Review-aware confirmation should include the exact confirmation strings and a
reviewer identity:

```json
{
  "confirmed_parameters": [
    "motion_correction: confirm parameters match study design",
    "filtering: confirm parameters match study design",
    "design_matrix: confirm parameters match study design"
  ],
  "confirmed_by": "reviewer@example.org"
}
```

When review metadata is supplied, the API requires all confirmation items and a
non-empty reviewer. It records `confirmed_parameters`, `confirmed_by`,
`confirmed_at`, and changes `not_used_for_execution` to `false`.

## Expected Input

Ask the caller for these fields. If any field is missing, make conservative
assumptions and record them in `metadata.ai_generation.assumptions`.

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

Return a FlowGraph with this shape:

```json
{
  "schema_version": "0.2.0",
  "flow_id": "draft-task-12345678",
  "name": "AI Draft: Task GLM",
  "description": "AI-generated candidate flow. Requires user review before execution.",
  "metadata": {
    "author": "ai-draft",
    "tags": ["task", "ai-generated"],
    "ai_generation": {
      "generated_by": "generative_ai",
      "model": "template_based",
      "created_at": "YYYY-MM-DDTHH:MM:SS+00:00",
      "input_summary": "",
      "assumptions": [],
      "requires_user_confirmation": [],
      "confirmed_parameters": [],
      "not_used_for_execution": true
    }
  },
  "nodes": [],
  "edges": []
}
```

Each atom should use this minimal shape:

```json
{
  "id": "n_optical_density",
  "type": "optical_density",
  "atom_type": "optical_density",
  "operation": "optical_density",
  "category": "preprocessing",
  "origin": "builtin",
  "position": {"x": 400, "y": 200},
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

Each edge should reference declared atom IDs and port handles:

```json
{
  "id": "e_n_optical_density_od_data_n_filtering_od_data",
  "source": "n_optical_density",
  "target": "n_filtering",
  "source_handle": "od_data",
  "target_handle": "od_data"
}
```

## Current Generator Behavior

`generate_draft_flow()` is template-based, not an LLM runtime. It uses the
scenario registry, the built-in node library, and preset defaults to create a
starting graph. Supported scenario IDs come from `ScenarioRegistry`, including
task, resting-state, and machine-learning oriented scenarios where available in
the registry.

The generator:

- creates `nodes` from required and optional scenario atom types
- connects compatible required ports by matching schemas
- marks high-impact atoms for review
- adds default assumptions such as data format and scenario name
- adds confirmation items for high-impact parameters such as motion correction,
  filtering, and design matrix settings
- leaves execution status as `not_run`

## Common Port Schemas

Use these port schema names when possible:

| Schema | Meaning |
|---|---|
| `DataManifest` | Discovered dataset manifest |
| `RawData` | Raw fNIRS data loaded by adapter |
| `DesignSpec` | Conditions, events, contrasts |
| `OpticalDensityData` | Optical density data |
| `QCReport` | QC metrics and channel decisions |
| `HemoglobinData` or `HaemoglobinData` | HbO/HbR concentration data |
| `DesignMatrix` | First-level GLM design matrix |
| `GLMResult` or `GLMResults` | First-level model output |
| `ContrastResult` or `ContrastResults` | Contrast estimates |
| `ConnectivityMatrix` | Resting or hyperscanning connectivity output |
| `MLFeatures` | Machine-learning features |
| `MLValidationReport` | ML split and leakage validation |
| `Report` | Report or checklist |
| `FlowPackage` | Export package |

## Scenario Skeletons

### Task GLM

```text
dataset_discovery
-> read_run
-> optical_density
-> qc_metrics
-> motion_correction
-> filtering
-> mbll
-> design_matrix
-> glm
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
- partial pathlength factor or MBLL settings
- short-channel/systemic regression decision
- ROI mapping
- package profile

### Resting-State Connectivity

```text
dataset_discovery
-> read_run
-> optical_density
-> qc_metrics
-> motion_correction
-> filtering
-> mbll
-> connectivity_analysis
-> channel_output or roi_output
-> reporting_checklist
-> package_export
```

Required confirmations:

- frequency band
- connectivity metric
- ROI or channel aggregation
- motion and systemic physiology handling
- multiple-comparison or graph-metric reporting plan

### Machine Learning Validation

```text
dataset_discovery
-> read_run
-> optical_density
-> qc_metrics
-> motion_correction
-> filtering
-> mbll
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
- grouped cross-validation policy
- held-out test policy
- fairness and inclusion audit fields

## Minimal Importable Example

This compact example is intentionally small. It demonstrates the metadata and
review contract; production drafts should include all atoms required by the
selected scenario and then pass fnirs-flow validation.

```json
{
  "schema_version": "0.2.0",
  "flow_id": "draft-task-example",
  "name": "AI Draft: Task GLM Example",
  "description": "Candidate task GLM flow requiring validation and user confirmation.",
  "metadata": {
    "author": "ai-draft",
    "tags": ["task", "ai-generated"],
    "ai_generation": {
      "generated_by": "generative_ai",
      "model": "template_based",
      "created_at": "2026-07-15T00:00:00+00:00",
      "input_summary": "Task GLM draft using a public BIDS-NIRS dataset.",
      "assumptions": ["Conditions and contrasts require confirmation."],
      "requires_user_confirmation": [
        "motion_correction: confirm parameters match study design",
        "filtering: confirm parameters match study design",
        "design_matrix: confirm parameters match study design"
      ],
      "confirmed_parameters": [],
      "not_used_for_execution": true
    }
  },
  "nodes": [
    {
      "id": "n_dataset_discovery",
      "type": "dataset_discovery",
      "atom_type": "dataset_discovery",
      "operation": "dataset_discovery",
      "category": "data",
      "origin": "builtin",
      "position": {"x": 100, "y": 200},
      "config": {"dataset_id": "bids-nirs-tapping", "source_kind": "bids_nirs"},
      "ports": [
        {"name": "data_manifest", "direction": "out", "schema": "DataManifest", "required": true}
      ],
      "readiness_status": "needs_attention",
      "execution_status": "not_run",
      "security_status": "trusted",
      "execution_trust_level": "builtin_managed"
    },
    {
      "id": "n_read_run",
      "type": "read_run",
      "atom_type": "read_run",
      "operation": "read_run",
      "category": "data",
      "origin": "builtin",
      "position": {"x": 300, "y": 200},
      "config": {},
      "ports": [
        {"name": "data_manifest", "direction": "in", "schema": "DataManifest", "required": true},
        {"name": "raw_data", "direction": "out", "schema": "RawData", "required": true}
      ],
      "readiness_status": "needs_attention",
      "execution_status": "not_run",
      "security_status": "trusted",
      "execution_trust_level": "builtin_managed"
    },
    {
      "id": "n_optical_density",
      "type": "optical_density",
      "atom_type": "optical_density",
      "operation": "optical_density",
      "category": "preprocessing",
      "origin": "builtin",
      "position": {"x": 500, "y": 200},
      "config": {},
      "ports": [
        {"name": "raw_data", "direction": "in", "schema": "RawData", "required": true},
        {"name": "od_data", "direction": "out", "schema": "OpticalDensityData", "required": true}
      ],
      "readiness_status": "needs_attention",
      "execution_status": "not_run",
      "security_status": "trusted",
      "execution_trust_level": "builtin_managed"
    }
  ],
  "edges": [
    {
      "id": "e_n_dataset_discovery_data_manifest_n_read_run_data_manifest",
      "source": "n_dataset_discovery",
      "target": "n_read_run",
      "source_handle": "data_manifest",
      "target_handle": "data_manifest"
    },
    {
      "id": "e_n_read_run_raw_data_n_optical_density_raw_data",
      "source": "n_read_run",
      "target": "n_optical_density",
      "source_handle": "raw_data",
      "target_handle": "raw_data"
    }
  ]
}
```

## Final Self-Check

Before returning or saving a draft:

- Every edge points to existing atom IDs.
- Every edge handle matches a declared port name.
- High-impact parameters appear in `requires_user_confirmation`.
- Custom executable atoms are avoided or quarantined.
- `metadata.ai_generation.not_used_for_execution` is `true` before review.
- The project draft is validated before confirmation.
- Review-aware confirmation records a reviewer and all required confirmations.
- The final output is valid JSON when the caller asks for machine-readable
  output.
