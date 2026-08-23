# MethodAtom Library QA Report

- Validation command: `.venv/Scripts/python.exe C:/Users/John/.codex/skills/literature-to-methodatom-library/scripts/validate_methodatom_library.py fnirs_flow/registry/methodatom_lib`
- Status: PASS
- Errors: 0
- Warnings: 0

## Object counts

- sources: 1640
- method atoms: 114
- parameter candidates: 417
- adapter definitions: 1
- flow slot contracts: 55
- risk rule candidates: 7
- reporting requirements: 8
- flow template candidates: 5
- evidence links: 3244

## Default promotion policy

No literature parameter is promoted merely because it is reported, inferred,
or common. Runtime defaults are created only for parameters explicitly marked
`project_default`. All other values remain in `parameter_candidates.csv` and
MethodAtom provenance metadata.

## Human review queue

- Bibliographic title, year, DOI, PMID, and full-text level are unavailable for
  many imported evidence links. These sources are retained as `metadata_only`
  records and require source-level enrichment before publication claims.
- The five flow-template rows remain `needs_attention`; their atom and slot
  sequences require scenario-owner approval.
- Unverified backend bindings remain `needs_attention` and are excluded from
  the executable Operation Registry.
