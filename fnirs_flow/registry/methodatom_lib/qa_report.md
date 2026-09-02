# MethodAtom Library QA Report

- Validation command: `tools/audit/rebuild_methodatom_qa_assets.py`
- Status: PASS
- Errors: 0
- Warnings: 0

## Object counts

- sources.csv: 1626
- method_atoms.csv: 114
- parameter_candidates.csv: 417
- adapter_definitions.csv: 1
- flow_slot_contracts.csv: 55
- risk_rule_candidates.csv: 7
- reporting_requirements.csv: 8
- templates.csv: 5
- atom_evidence_links.csv: 3222

## Default promotion policy

Only parameters explicitly marked `project_default` are executable. Reported, inferred, and candidate values remain non-executable.

## Human review queue

- External bibliographic validation remains pending; local metadata is not represented as external verification.
- Flow templates and backend-specific bindings require scenario-owner review before execution.
- Evidence links missing claim, study, locator, or extraction-review fields remain fallback-only in the Evidence Readiness Audit.

## Repository quality gates

- Package CSVs are the sole source for this report and manifest.
- `outputs/methodatom_library` is an exact generated mirror.
