# Vendor-Processed Hb Analysis

This specification defines a reusable analysis branch for vendor-processed
haemoglobin time series. It is intentionally independent of any research
project, intervention, dataset, clinical indication, or fixed condition set.

## Data semantics

`vendor_processed_hb` is a data branch, not a MethodAtom. A complete flow uses
eight MethodAtoms:

1. `frozen_manifest_discovery`
2. `read_vendor_processed_hb`
3. `ingest_frozen_events`
4. `regularize_processed_hb_time`
5. `compile_processed_hb_designs`
6. `fit_processed_hb_first_level`
7. `estimate_full_contrasts`
8. `write_processed_hb_derivatives`

The input is already converted to HbO/HbR and may include HbT for consistency
checks. The branch must not claim or reconstruct raw intensity, optical density,
motion correction, filtering, short-channel regression, or MBLL processing.
Absolute concentration units remain unverified unless independently established
by input provenance.

## Portable input contract

Discovery joins a signal-provenance table and a population table exclusively by
`fnirs_record_id`. Optional cross-modal identity uses the neutral
`linked_record_id`; `record_pair_id` is the stable analysis-unit key. Runtime
local paths are excluded from serialized manifests. Portable signal references
use `external-data://vendor-processed-hb/<filename>` and are rebound explicitly
when a package is imported.

The event and contrast tables are authoritative inputs. Unknown columns,
duplicate identifiers, non-finite timing, missing model definitions, and
non-estimable contrasts fail closed.

## Generic design models

The default experimental preset provides three reusable model structures:

- `glm_conditions_canonical_td_v1`: one canonical HRF and temporal derivative
  pair per unique input condition.
- `fir_post_event_0_30_10s_v1`: pooled post-event FIR bins from 0 to 30 seconds.
- `glm_event_order_linear_canonical_td_v1`: an aggregate event response plus a
  centered linear event-order modulation for two or more events.

Condition labels and event counts come from the frozen event table. No model
assumes a study-specific label sequence. Contrast definitions bind by model ID
and regressor name, never by column position.

## Statistical and release constraints

The default solver request is AR(1) plus robust IRLS with explicit covariance
and diagnostics. Fallback is forbidden unless the caller opts into a documented
alternative. Design hashes bind normalized events, the regularized time axis,
model parameters, matrix bytes, contrast definitions, and the contrast-table
hash.

The bundled preset is experimental and is not suitable for confirmatory
inference until every scientific threshold is supplied and marked frozen.
Software must not infer project-specific QC cutoffs. Outputs are written below
`derivatives/processed_hb_first_level` with provenance, exclusion decisions,
design metadata, coefficients, covariance, contrasts, QC, and audit tables.

## Naming gate

All public paths and text must pass the generic naming gate defined in
`PUBLIC_SYNC_SPEC.md`. Research-specific project, dataset, intervention,
condition-sequence, freeze, and model names are prohibited from code, configs,
tests, documentation, evidence records, and generated WebUI assets.
