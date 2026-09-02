# fnirs-flow Public API Contract

Version: 1.3.0
Updated: 2026-09-02

This document defines the stable public surface of fnirs-flow. Any breaking change to these surfaces requires a schema version bump and changelog entry.

## 1. Core Models

### FlowGraph

Top-level canonical flow container. Current schema version `0.3.0`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | `string` | yes | Currently `"0.3.0"` |
| `flow_id` | `string` | yes | Unique flow identifier |
| `name` | `string` | yes | Human-readable name |
| `description` | `string` | no | Free-text description |
| `flow_atoms` | `list[FlowAtom]` | yes | Canonical atom collection |
| `edges` | `list[FlowEdge]` | yes | Directed edges between atoms |
| `adapter_registry` | `list[AdapterDefinition]` | no | Registered adapters |
| `metadata` | `FlowMetadata` | no | Author, tags, timestamps |

### FlowAtom

Business-level flow atom instance. `FlowNode` remains a public class alias, but
its constructor and in-memory representation use the canonical fields below.
Historical JSON fields are accepted only through
`fnirs_flow.flow.serialization.load_canonical_flow()` and the schema loading
helpers.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | `string` | yes | Unique atom instance ID |
| `atom_type` | `string` | yes | Canonical MethodAtom type |
| `template_id` | `string \| null` | no | Reference to atom library template |
| `operation` | `string \| null` | no | Operation name |
| `evidence_refs` | `list[string]` | no | Literature evidence references |
| `category` | `MethodAtomCategory` | yes | One of: `data`, `design`, `preprocessing`, `analysis`, `output`, `validation`, `export` |
| `origin` | `MethodAtomOrigin` | no | One of: `builtin`, `evidence_derived`, `user_created`, `imported` |
| `position` | `Position` | no | Canvas position (x, y) |
| `config` | `dict` | no | Atom-specific configuration |
| `ports` | `list[AtomPort]` | no | Input/output ports |
| `adapter_bindings` | `list[AdapterInstance]` | no | Bound adapter instances |
| `execution_trust_level` | `ExecutableTrustLevel` | no | Trust level for execution |
| `readiness_status` | `ReadinessStatus` | no | Current readiness state |
| `execution_status` | `ExecutionStatus` | no | Current execution state |
| `security_status` | `SecurityStatus` | no | Security/trust state |

### FlowEdge

Directed edge between two atoms.

| Field | Type | Required |
|---|---|---|
| `id` | `string` | yes |
| `source` | `string` | yes |
| `target` | `string` | yes |
| `source_handle` | `string` | yes |
| `target_handle` | `string` | yes |
| `adapter_id` | `string \| null` | no |

### AtomPort

Input/output port on a FlowAtom.

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | `string` | yes | Port name |
| `direction` | `string` | yes | `"in"` or `"out"` |
| `schema` | `string` | yes | Port schema type (see Port Schemas) |
| `required` | `boolean` | no | Default: `true` |

### MethodAtomTemplate Parameter UI Metadata

The `/api/atom-templates` endpoint returns parameter UI metadata owned by each atom template:

| Field | Type | Notes |
|---|---|---|
| `parameter_options` | `dict[str, list[Any]]` | Fixed candidate values for select controls. |
| `parameter_specs` | `dict[str, dict[str, Any]]` | Per-parameter control metadata, including `type`, `control`, `description`, `placeholder`, `advanced`, `minimum`, `maximum`, and `range`. |

WebUI parameter rendering must consume these fields instead of hardcoding atom-specific parameter names. See `docs/specs/method_atom_parameter_ui_contract.md` for the full contract.

## 2. Port Schema Types

These schemas define data type compatibility between connected atoms.

| Schema ID | Description |
|---|---|
| `RawIntensity` | Raw fNIRS intensity data |
| `OpticalDensity` | Optical density data |
| `HaemoglobinData` | HbO/HbR/HbT concentration data |
| `EventsTable` | Experimental events/conditions table |
| `DesignMatrix` | Statistical design matrix |
| `ContrastSpec` | Contrast definition for GLM |
| `QCReport` | Quality control report |
| `ChannelSummary` | Channel-level summary statistics |
| `ROISummary` | ROI-level summary statistics |
| `RiskRegister` | Risk assessment register |
| `PackageManifest` | Reproducible package manifest |
| `StatsTable` | Statistical results table |

## 3. Adapter Surfaces

### AdapterDefinition

| Field | Type | Required |
|---|---|---|
| `adapter_id` | `string` | yes |
| `name` | `string` | yes |
| `source_type` | `string` | yes |
| `target_type` | `string` | yes |
| `transform` | `string` | no |
| `parameters` | `dict` | no |

### AdapterInstance

| Field | Type | Required |
|---|---|---|
| `definition_id` | `string` | yes |
| `parameters` | `dict` | no |

## 4. Package Profiles

| Profile ID | Contents | Use Case |
|---|---|---|
| `reproducibility_package` | plan.json, execution_dag.json, data_manifest.json, all manifests, validation_report.md, analysis_plan.md | Full reproducibility |
| `submission_package` | plan.json, analysis_plan.md, risk_register.json, validation_report.md | Journal submission |
| `reviewer_package` | All of above + provenance_log.json, failure_manifest.json | Peer review |

## 5. Artifact Record

Every adapter step must emit an artifact record:

```json
{
  "artifact_id": "string",
  "artifact_type": "RawIntensity|OpticalDensity|HaemoglobinData|QCReport|DesignMatrix|StatsTable|ChannelSummary|ROISummary",
  "path": "string",
  "checksum": "string",
  "software": {
    "mne": "string",
    "mne_nirs": "string",
    "mne_bids": "string"
  },
  "parameters": {},
  "subject": "string",
  "session": "string",
  "run": "string"
}
```

## 6. ActionAttempt

Tracks execution attempts at subject/session/run granularity.

| Field | Type | Required |
|---|---|---|
| `attempt_id` | `string` | yes |
| `subject` | `string` | yes |
| `session` | `string` | yes |
| `run` | `string` | yes |
| `status` | `ActionAttemptStatus` | yes |
| `started_at` | `string` | yes |
| `completed_at` | `string \| null` | no |
| `atom_id` | `string` | yes |
| `error_type` | `string \| null` | no |
| `error_message` | `string \| null` | no |
| `recoverable` | `boolean` | no |
| `log_path` | `string \| null` | no |

### ActionAttemptStatus

`planned` | `running` | `completed` | `failed` | `partial`

## 7. FailureRecord

Structured failure information.

| Field | Type | Required |
|---|---|---|
| `failure_id` | `string` | yes |
| `subject` | `string` | yes |
| `session` | `string` | yes |
| `run` | `string` | yes |
| `atom_id` | `string` | yes |
| `exception_type` | `string` | yes |
| `message` | `string` | yes |
| `recoverable` | `boolean` | yes |
| `log_path` | `string \| null` | no |
| `timestamp` | `string` | yes |

## 8. Typed Error Codes

| Code | Severity | Domain | Description |
|---|---|---|---|
| `atom-compat-version-unsatisfied` | fatal | security | Atom requires fnirs-flow version that is not satisfied |
| `atom-manifest-missing` | fatal | security | Custom atom has no capability_manifest |
| `atom-path-escape` | fatal | security | Atom requests file access outside project root |
| `atom-shell-forbidden` | fatal | security | Atom requests shell execution capability |
| `adapter-schema-mismatch` | high | adapter | Source/target port schemas are incompatible |
| `adapter-ambiguous` | medium | adapter | Multiple adapters could satisfy a connection |
| `package-profile-unsupported` | fatal | export | Requested package profile does not exist |
| `flow-cycle-detected` | fatal | graph | Flow graph contains a cycle |
| `flow-missing-contrasts` | medium | design | No contrasts defined for statistical analysis |
| `flow-missing-events` | high | design | No events table provided for task-based analysis |
| `qc-sci-below-threshold` | medium | qc | SCI below quality threshold |
| `qc-sd-distance-invalid` | high | qc | Source-detector distance outside valid range |
| `qc-no-short-channels` | medium | qc | No short channels but systemic regression requested |
| `reproducibility-no-seed` | low | reproducibility | No random seed specified |
| `harmonization-site-missing` | fatal | harmonization | Site field missing for ComBat harmonization |
| `harmonization-site-confounded` | high | harmonization | Site completely confounded with group variable |
| `harmonization-insufficient-samples` | high | harmonization | Insufficient samples per site |

## 9. Execution Directory Layout

```
outputs/<project_id>/
├── compiled/
│   ├── plan.json
│   ├── execution_dag.json
│   └── manifests/
├── work/
├── derivatives/
│   ├── sub-<label>/
│   │   └── ses-<label>/
│   │       └── nirs/
│   │           ├── *_desc-preproc_hbo.tsv
│   │           ├── *_desc-qc_channels.tsv
│   │           └── *_desc-firstlevel_stats.tsv
│   ├── group/
│   └── reports/
│       ├── sub-<label>_desc-run_report.html
│       ├── sub-<label>_desc-session_report.html
│       └── sub-<label>_desc-subject_report.html
└── logs/
    ├── run_history.jsonl
    └── failure_manifest.json
```

## 10. CLI Commands

```
fnirs-flow run <flow-or-package> --dataset <bids_dir> --out-dir <out> [--participant-label ...]
fnirs-flow validate <flow-or-package> [--profile reproducibility_package]
fnirs-flow dry-run <flow-or-package> --dataset <bids_dir> [--write-report]
fnirs-flow reports-only <compiled_dir> [--subject-label ...]
fnirs-flow export <compiled_dir> [--profile submission_package]
```

## Versioning

- Breaking changes to any surface above require a `schema_version` bump.
- Additive changes (new optional fields, new port schemas, new error codes) are non-breaking.
- Deprecated fields are kept for one major version with a deprecation warning.
