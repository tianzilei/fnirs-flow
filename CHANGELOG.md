# Changelog

## [Unreleased] - 2026-08-27

### Added

- Started the post-release evidence-system E0 implementation with versioned
  source/claim/event/snapshot contracts, enumerated reason codes and role
  boundaries, an append-only hash-chained Evidence Store, atomic QA-gated
  snapshot publication and rollback verification, and conservative dry-run
  CSV migration. The migration regression accounts for all 3,222 packaged
  links and keeps every unreviewed legacy record in `needs_repair`.
- Added a generic vendor-processed Hb branch composed from eight MethodAtoms,
  including strict manifest discovery, event ingestion, time regularization,
  reusable design compilation, first-level solving, full contrasts, derivative
  output, and release-acceptance evidence.
- Added `docs/specs/vendor_processed_hb_analysis.md` and public CLI guidance for
  the experimental processed-Hb workflow.
- Added a case-insensitive public naming gate for filenames and UTF-8 content,
  with regression tests and policy requirements in `PUBLIC_SYNC_SPEC.md`.
- Removed dataset-specific real-data benchmark scripts, configurations, and
  fixtures from the public synchronization whitelist; public examples now use
  domain-neutral data paths.

### Changed

- Completed the processed-Hb public-contract generalization by replacing the
  residual study-specific paired-record field with `paired_record_id` and the
  fixed-count model label with `EVENT-SERIES`.
- Made the public sync tree self-contained for the documented processed-Hb CLI
  while explicitly excluding only development tests that require private
  `outputs/` artifacts or internal audit tools.
- Limited the release license policy gate to declared direct dependencies, as
  documented, while allowing uninstalled optional dependencies only when they
  are explicitly covered by `THIRD_PARTY_NOTICES.md`.
- Removed the hard-coded claim that revision-specific browser and vulnerability
  gates had passed from the readiness inventory.
- Generalized processed-Hb dataset, preset, operation, identity, and model IDs
  so they no longer encode a particular project, intervention, condition
  sequence, clinical indication, or analysis freeze.
- Removed research-specific literature records and their evidence links from
  the bundled MethodAtom library, and normalized non-portable evidence paths.
- Rebuilt packaged WebUI assets after the identifier changes.
- Made the Shimadzu OMM preset generic and canonical across both preset APIs;
  recording-specific condition values now come only from parsed input headers.
- Added Python-version markers so Python 3.13 resolves to NumPy 2.1 or newer.

### Fixed

- Removed the public processed-Hb split command's dependency on excluded
  development modules and replaced private-data tests with synthetic fixtures.
- Made Shimadzu layout parsing fail closed for proprietary or malformed binary
  files instead of inventing wavelengths or channel geometry.
- Kept Shimadzu Applied Voltage and Amp. Gain rows separate and reject
  ambiguous, conflicting, or count-mismatched condition metadata.
- Applied the shared macOS metadata filter to source, atom, inventory, package,
  output-manifest, and governance scanners used on AppleDouble-producing disks.
- Replaced warning-prone matrix products and pseudoinverse reconstruction with
  finite-checked contractions for Python 3.13 numerical compatibility.
- Restored ASCII-safe package-verifier output and all Ruff/layered-mypy gates.

### Validation

- Development Python suite: 1,449 passed, 3 skipped.
- Clean public Python suite: 1,429 passed, 13 skipped.
- Ruff and the core/MNE mypy profiles passed.
- WebUI unit tests: 26 passed; production build and locked npm dependency audit
  passed with 0 vulnerabilities.
- Playwright Chromium/Firefox/WebKit matrix: 36 passed, 1 opt-in real-data
  scenario skipped.
- Rebuilt wheel and sdist passed package-content checks, isolated wheel
  installation, CLI smoke, API health, packaged registry, and static-asset
  black-box checks.
- Public synchronization dry-run, English-only gate, generic naming gate, and
  full-repository prohibited-term scan passed.
- Python and npm dependency audits reported no known vulnerabilities.

## [1.3.0] - 2026-08-28

### Added

- Added evidence-readiness contracts and deterministic recommendation decision
  persistence with explicit re-evaluation and provenance anchors.
- Added a reproducible 3,222-row evidence inventory, a five-slot claim repair
  queue, source-locator accessibility checks, and fail-closed evidence-mode
  decision construction that cannot produce a best recommendation before
  calibration.

### Changed

- Completed the v1.3.0 recommendation-system engineering layer: deterministic
  candidate decisions, method/execution checks, immutable persistence, API and
  package provenance, WebUI explanations, and user confirmation are released
  through static/shadow/fallback paths.
- Kept the evidence system as a separate follow-up workstream. Evidence-driven
  ranking remains disabled until claim review, calibration, and holdout gates
  are completed; this does not affect Flow analysis execution.

### Validation

- v1.3.0 RC readiness audit passed with 10 checks and zero release blockers.
- P6 calibration/holdout validation is decoupled from Flow analysis; absent
  annotation data is reported as `unverified` and remains a post-release task.
- Full Python suite: 1,412 passed, 2 skipped; Ruff, package, license/notice,
  pip-audit, npm-audit, OpenAPI, and WebUI unit/build gates passed.
- Complete Playwright matrix passed across Chromium, Firefox, and WebKit
  (`36 passed, 1 skipped`); the skipped test is the opt-in real-data scenario.

## [1.2.5] - 2026-08-23

### Changed

- Reconciled development and public release metadata after v1.2.4 so future
  clean synchronizations preserve the published version history instead of
  reverting public version declarations.
- Regenerated the public release manifest from the explicit 433-file
  whitelist and reviewed all required public Markdown for the English-only
  release policy.

### Validation

- Development suite: 1,299 passed, 2 skipped.
- Clean public suite: 1,288 passed, 13 skipped.
- Ruff passed for `cli.py fnirs_flow tests scripts tools`.
- WebUI unit tests: 24 passed; development build passed.
- `npm audit --audit-level=moderate`: 0 vulnerabilities.
- Public release dry-run, clean synchronization, forbidden-path audit,
  English-only scan, and release-version consistency checks passed.

## [1.2.4] - 2026-08-23

### Fixed

- Corrected MethodAtom execution semantics and backend contracts across the
  MNE-NIRS adapter, QC operations, filtering, motion correction, ROI output,
  and compile-gate backend validation.
- Added executable scientific and deep-learning MethodAtom handlers and
  synchronized the public MethodAtom evidence, parameter, slot, risk, and
  reporting assets.
- Added the public release validation coverage for the synchronized handlers
  and evidence-library assets.

### Validation

- Public Python suite: 1,287 passed, 13 skipped.
- Stratified numerical comparison: 9 runs and 81 operation checks
  passed within `rtol=1e-10`, `atol=1e-12`.
- All completed real-data comparisons: 55 runs and 495 operation checks passed
  within the same tolerances.
- Independently installed wheel black-box checks passed.

## [1.2.3] - 2026-08-21

### Fixed

- Corrected run-scope signal routing so design matrices and other typed
  analysis outputs no longer create false Raw-data fan-in conflicts at GLM
  joins.
- Ensured failed atoms always finalize their run as failed, including with
  `--no-continue-on-failure`; CLI execution now also returns nonzero when runs
  are skipped because their data paths cannot be resolved.
- Added `discover --data-root`, normalized BIDS-prefixed execution filters,
  preserved explicit empty-ROI warnings, and made backend status output safe
  for non-UTF-8 Windows consoles.

### Validation

- Full development suite: `1256 passed, 2 skipped`.
- Clean public suite: `1245 passed, 13 skipped`.
- Public WebUI: 24 unit tests passed; development build and npm audit passed
  with 0 known vulnerabilities.
- Wheel and sdist builds passed package-content checks; the independently
  installed wheel passed the API, schema, WebUI-resource, and MethodAtom
  black-box checks.
- Installed-wheel BIDS-NIRS tapping acceptance: 5 successful runs, 0 failed,
  0 skipped.

## [1.2.2] - 2026-08-21

This release records the current synchronized development and public trees.

### Release metadata

- Project version is `1.2.2` across Python, WebUI, API metadata, and public documentation.
- Public release synchronization and English-only documentation checks passed.
- Repository-hosted CI/CD workflows have been removed. Release validation is
  run locally, and verified distributions are published manually to GitHub
  Releases.

### Verified - 2026-08-21 Public Sync

- Clean public tree: `1235 passed, 13 skipped` with pytest.
- `ruff check cli.py fnirs_flow tests scripts tools`: passed.
- WebUI unit tests: 24 passed.
- WebUI production build: passed.
- `npm audit`: 0 known vulnerabilities.
- Public release dry-run, forbidden-path audit, English-only scan, local
  Markdown link check, and all 422 manifest hash checks passed.

### Added

- Validated `FNIRS_RUN_WORKERS`, `FNIRS_BLAS_THREADS`,
  `FNIRS_PARALLEL_BACKEND`, and `FNIRS_MEMORY_BUDGET_MB` settings with effective
  CPU/memory admission, runtime native-thread limits, and audit metadata.
- Spawn-safe, opt-in run process backend with scalar/path-only worker contracts,
  deterministic input-order aggregation, API-thread coverage, cooperative
  cancellation polling, and no post-start serial retry.
- Deterministic execution benchmark runner and CI artifact upload.
- ADR-0006 read-migrate/canonical-write policy for legacy Flow/DAG fields.

### Changed

- Removed the public GitHub Actions CI and release workflows; local release
  checks remain available under `tools/release/`.
- Updated the public documentation index and release notices so every shipped
  document is self-contained, English-only, and limited to files present in the
  public release tree.
- Participant-table and group-statistics implementations now live behind their
  dedicated modules; `data.participants` is a deprecated re-export facade.
- MNE preprocessing and first-level analysis implementations now live behind
  stage-specific modules; `mne_nirs_steps` is a deprecated re-export facade.
- IIR filtering is vectorized across channels.
- Group permutations use deterministic `SeedSequence` streams, reuse invariant
  matrix inverses, expose seed/chunk/execution audit fields, and check
  cancellation at chunk boundaries.
- Registry CSV loading rejects missing and duplicate MethodAtom IDs.

### Verified

- Full suite (`1212 passed, 2 skipped`), Ruff, core mypy (`170` files), and
  MNE mypy (`9` files) passed.
- CPU-bound four-run benchmark, three-run medians: `9.03 s` serial vs `4.74 s`
  with four processes (`1.90x`), with identical result digests.
- Real two-run SNIRF serial/process orchestration matched status, artifact
  identity/type/checksum, atom status, and numerical result tables.
- DAG-layer parallelism remains disabled because run-level processing removes
  the measured bottleneck and small workloads regress under extra scheduling.

## [1.2.1] - 2026-08-19

- Synchronized the development and public release trees at version `1.2.1`.
- Added public CI gates for architecture, runtime, generated contracts,
  packaging, security, licenses, WebUI, browser tests, and release versions.
- Added verified-distribution publishing from version tags to GitHub Releases.

## [1.2.0] - 2026-07-15

### Verified — 2026-08-15 Public Sync

- Clean public tree `pytest -q`: 1149 passed, 11 skipped
- Development tree `pytest -q`: 1158 passed, 2 skipped; nine additional passes use excluded local real-data fixtures
- `ruff check cli.py fnirs_flow tests scripts`: passed
- `npm run test:unit`: 22 passed
- `npm run build`: passed with the existing Vite chunk-size warning
- Public release English-only gate: passed across all 287 whitelisted source files
- Public release manifest self-check: all copied and generated file hashes matched
- CI covers Python 3.10–3.13; Python 3.10 resolves MNE below 1.13
- `npm audit --audit-level=moderate`: 0 vulnerabilities after compatible lockfile updates

### Added — 2026-07-18 Release Convergence

- Flow Checklist guidance panel for Task GLM, resting-state connectivity, group analysis, and ML classification workflows
- Checklist-to-Atom Library recommendation flow with `Best fit`, `Recommended`, and `Alternative` ranking
- Checklist `Next:` action banner, priority-step highlighting, recommendation reasons, focused atom navigation, and guided missing-atom preview
- Order-risk and Empty-risk controls for reviewed order violations and no-op processing markers
- Empty-risk reverse sync: disabling the risk removes generated empty atoms and clears checklist skip state
- Canvas-level badges for checklist focus, missing required inputs, and empty/no-op atoms
- Checklist JSON report export with step status, missing inputs, skip reasons, and link state
- Group/second-level result exports for direct review in the Results Workspace:
  - `group_glm_results.csv/json`
  - `contrast_results.csv/json`
  - `contrast_matrix.csv`
  - `effect_sizes.csv/json`
  - `multiple_comparison_results.csv/json`
  - `contrast_effects.svg`
- Results API support for group SVG figures, rendered directly in the WebUI Group tab
- Frontend unit tests for checklist atom orchestration helpers

### Changed — 2026-07-18 Release Convergence

- Atom Library now auto-focuses the Checklist tab after selecting a checklist step, reducing atom selection noise.
- Group contrast atom parameters are merged into group configuration during group-scope execution.
- Manual drag outside the active checklist step is warned but not blocked.
- WebUI remains English-only; no Chinese UI strings are introduced.

### Verified — 2026-07-18 Release Convergence

- `ruff check cli.py fnirs_flow tests scripts/evaluate_validation_gold.py`: passed
- `pytest -q`: 1126 passed, 1 skipped
- `npm run test:unit`: 9 passed
- `npm run build -- --mode development`: passed with the existing Vite chunk-size warning
- `npx playwright test e2e/workflows.spec.ts`: 6 passed
- WebUI Chinese-character scan: no UI strings found in `webui/src`, `webui/e2e`, or `webui/tests`
- CLI smoke: `python cli.py --help` and `python -m fnirs_flow.cli --help` passed
- Real WebUI smoke: Checklist `Next:` CTA, recommendation reason, priority step, Group UI routing, no Chinese UI text, and no horizontal overflow

### Added — FlowVCS (Design History)

FlowVCS is a content-addressed version control system for `.fnirsflow` project files.
Implemented in `fnirs_flow/history/` with no external dependencies (no Git CLI, no SQLite).

- Commit, branch, checkout, diff, and restore operations for FlowGraph designs
- SHA-256 content-addressed object storage with automatic deduplication
- ZIP JSON store with sharded objects and state persistence
- Legacy `ProjectSnapshot` migration into FlowVCS history
- History API endpoints (initialize, commit, branch, checkout, diff, list)
- WebUI Design History Panel for commit, branch, checkout, diff, and legacy migration
- Transaction-level HEAD concurrency control
- Cross-machine bundle preservation verified
- **Phase 4 acceptance**: 10 MiB history budget, object dedup, fail-closed corruption, cross-platform reading

Status: stable for the 1.2.0 release line; semantic merge remains deferred.

### Added — AI Draft Contract

- Independent draft state: `pending_draft` stored separately from current flow
- Generate, get, validate, confirm, discard draft endpoints
- Draft validation with risk/readiness assessment without confirming
- CLI `generate-flow-draft` command
- Schema-compliant draft generation with proper position, handle, and readiness fields
- WebUI review panel with current-vs-draft diff, assumptions, validation risks, and explicit confirmations
- Human reviewer, confirmation timestamp, and exact confirmed parameters recorded before applying a draft
- Schema-compatible port wiring; task drafts now produce no schema or graph validation errors

### Changed

- Version boundary: v1.1.1 tag created at commit 6104137b
- Version finalized as 1.2.0 after FlowVCS, AI Draft Review, package rerun, and real-data gates passed

### Fixed

- Imported package reruns now use local `external-data://` URI bindings when packaged `data_manifest.json` keeps `local_root` empty for portability.
- API project relink no longer writes machine-local URI bindings into the bundled `outputs/` tree.

### Deferred

- Semantic merge support (Phase 5, optional)

## [1.1.1] - 2026-07-14

> FlowVCS design history is implemented and tested but marked as a 1.2+ feature.
> It is available in this release for evaluation; the API is not yet frozen.

### Fixed
- Quarantine bundles (`corrupt-*.fnirsflow`) no longer consume retained revision slots
- API flow update endpoint now uses debounce to avoid excessive saves on rapid edits
- Added per-file size limit (8 MiB) and compression ratio guard (zip bomb protection)
- ADR-0004 SQLite v2 references replaced with ADR-0005 revocation notice across all docs
- Homer3/AnalyzIR adapter status corrected to bidirectional (import + export)
- Test counts unified to 858 passed, 1 skipped across all documentation

### Added
- Save/restore/migration failure injection tests
- Cross-directory/cross-machine bundle move tests
- Change detection and hash caching for flow-only saves
- 100 project cold start benchmark
- 1/4/8 MiB compliant bundle benchmarks and 10 MiB boundary tests

### Changed
- RC-5 SQLite section in release plan marked as revoked by ADR-0005
- KNOWN_LIMITATIONS updated to reflect current RC status
- CURRENT_DOCUMENTATION_MAP refreshed with all RC/audit documents

## [1.1.0] - 2026-07-14

### Added - Release Candidate Features

#### Integrity & Durability (RC-1)
- Real integrity status tracking (`unknown`, `checking`, `verified`, `failed`, `recoverable`)
- Added `integrity_status`, `last_verified_at`, `verification_scope`, `integrity_error` fields
- Added `fsync` calls for data durability during saves
- Corrupt projects are now visible in project list with `failed` status

#### Portability & Recovery (RC-2)
- Project-relative URI system (`project://` and `external-data://`)
- URI binding management for external datasets
- Version history API mounted in the Project Workspace
- Confirmed project restoration with success/error feedback and refreshed revision state
- Portable artifact, provenance, result-index, relink, and package-rerun URIs

#### Performance (RC-3)
- Lazy loading mode for project bundles
- `read_bundle_header` method for reading project metadata without full extraction
- `ensure_project_loaded` method for on-demand full loading
- Debounce primitives for `update_flow`; WebUI autosave integration remains deferred
- Formal 100/500/1000 MiB mixed and incompressible bundle benchmarks
- ADR-0005 decision to retain ZIP v1 as sole container format; ADR-0004 SQLite v2 prototype revoked

#### Scientific Reproducibility (RC-4)
- Three-entry-point consistency (CLI, API, WebUI)
- Real-data dataset reproducibility tests passing
- RC checklist, upgrade guide, rollback guide, and known limitations documentation

#### Type Safety
- Added reproducible core/MNE/Cedalion Mypy profiles and CI gates
- Added type annotations for numpy arrays
- Fixed implicit Optional parameters

### Validation note

- The 2026-07-14 correctness pass fixed project URI parsing and traversal safety, made project listing genuinely lazy,
  replaced the invalid synthetic performance benchmark, and increased the final test baseline to 858 passed, 1 skipped.
- A clean export/import/relink/rerun compared 12,493 numeric elements with a maximum absolute difference
  of `6.404987651364991e-12` at `rtol=1e-8`, `atol=1e-10`.
- Python and npm vulnerability audits finished with 0 known vulnerabilities. Pytest was raised to `>=9.0.3`
  after the initial scan detected `PYSEC-2026-1845` in the prior development environment.

## [1.0.4] - 2026-07-12

### Added - Cedalion Unique Features as MethodAtoms

#### New MethodAtoms (17 atoms)

**DOT (Diffuse Optical Tomography)**
- `ATOM_dot_head_model` - Two-surface head model construction from segmentation masks
- `ATOM_dot_forward_model` - Monte Carlo / FEM forward model simulation for light transport
- `ATOM_dot_image_recon` - DOT image reconstruction with Tikhonov or spatial basis function regularization
- `ATOM_dot_tissue_properties` - Tissue optical properties configuration (absorption, scattering, refractive index)

**Geometry / Photogrammetry**
- `ATOM_photogrammetry_coregistration` - Photogrammetric optode co-registration from 3D scans using colored sticker detection

**Signal Decomposition**
- `ATOM_spoc_decomposition` - Spatial Patterns of Covariance (SpOC) for neural decoding
- `ATOM_ica_signal_decomposition` - ICA-based signal decomposition (EBM/ERBM methods)
- `ATOM_multimodal_signal_decomposition` - Multimodal decomposition (MSPoC, tCCA, ARC-EBM/ERBM)

**Synthetic Data Generation**
- `ATOM_synthetic_hrf_generation` - Synthetic hemodynamic response function generation with spatial activation
- `ATOM_synthetic_artifact_generation` - Synthetic motion artifact generation for testing

**Machine Learning Utilities**
- `ATOM_epoch_feature_extraction` - Epoch feature extraction (slope, mean, max, min, AUC) for scikit-learn pipelines

**GLM (General Linear Model)**
- `ATOM_glm_basis_functions` - Temporal basis functions (Gamma, Gaussian kernels, Dirac delta)
- `ATOM_glm_design_matrix` - GLM design matrix construction with drift and short-channel regression
- `ATOM_glm_fit_with_uncertainty` - GLM fitting with confidence and prediction intervals

**Quality Control**
- `ATOM_psp_quality_metric` - Peak Spectral Power quality metric for channel assessment

**Preprocessing Configuration**
- `ATOM_channel_distance_computation` - Source-detector channel distance computation
- `ATOM_extinction_coefficients` - Molar extinction coefficients lookup (Prahl spectrum)

#### Updated Adapter

- **cedalion_capabilities.py**: Updated operation detection to support all new cedalion modules (DOT, signal decomposition, synthetic data, ML utilities, geometry)
- **cedalion_steps.py**: Added 18 new wrapper functions for cedalion operations
- **cedalion_adapter.py**: Added 18 new adapter methods with provenance and artifact tracking

#### Statistics

- MethodAtom library: 96 → 113 templates (+17)
- Cedalion adapter methods: 8 → 26 (+18)
- All new atoms tested and verified

## [1.0.3] - 2026-07-12

### Added - Cedalion Backend Integration & Evidence Governance

#### WP0: Baseline & Scope Lock
- Unified version to 1.0.2 across `pyproject.toml`, `__init__.py`, and `webui/package.json`
- Fixed all Ruff linting issues (19 errors resolved)
- Added pytest markers for core/full/cedalion/adapter test separation (39 core tests identified)
- Locked WebUI clean build with updated dependencies and CI using `npm ci`
- Created baseline audit script and JSON report

#### WP1: Execution Backend Abstraction
- **Backend Protocol** (`fnirs_flow/adapters/backend_protocol.py`): Typed protocol for execution backends
- **Backend Registry** (`fnirs_flow/adapters/backend_registry.py`): Registration, detection, and factory for MNE/Cedalion backends
- **BackendBinding model**: Added to `FlowAtom` and `DagNode` for explicit backend assignment
- **Compiler semantics**: Separated Edge Adapter from Execution Backend concepts
- **Execution factory**: Updated to use backend registry instead of hardcoded MNE adapter
- **Schema migration**: Updated to v0.3.0 with BackendBinding support
- **Mixed backend gating**: Validation for MNE-Cedalion connections without bridges

#### WP2: Cedalion MVP Adapter
- **Capability detection** (`cedalion_capabilities.py`): Detect Cedalion installation, version, compatibility
- **Data contract** (`cedalion_io.py`): SNIRF/Recording format definitions
- **Step wrappers** (`cedalion_steps.py`): `int2od`, `od2conc`, SNIRF reading
- **Adapter implementation** (`cedalion_adapter.py`): Full adapter with artifacts, provenance, citations
- **MethodAtom templates**: Added Cedalion-specific templates with backend bindings
- **CLI/API**: Added `backends` command and `/api/backends` endpoint
- **Optional dependency**: Added `cedalion` as optional dependency in `pyproject.toml`

#### WP3: Package, Methods & Evidence Chain
- **Package verifier** (`package_verifier.py`): Validate profile, schema, checksum, backend manifest
- **Evidence ID tracking**: Added `evidence_refs` to `AtomExecutionResult`
- **Methods reporting**: Enhanced to support evidence references
- **Backend tracking**: Package includes backend ID/version/capabilities
- **Numerical tolerance**: Created specification document

#### WP4: Validation Gold Standard & Backend Equivalence
- **Gold standard flows**: Created test flows for valid, invalid order, missing metadata, backend mismatch
- **Gold evaluator** (`evaluate_validation_gold.py`): Script to evaluate validation results
- **Integration tests**: Created MNE/Cedalion equivalence and SNIRF smoke tests
- **Backend comparison** (`compare_backends.py`): Script to compare MNE and Cedalion operations

#### WP5: WebUI/API Minimal Integration
- **Backend diagnostics**: Added `/api/backends` endpoint and SystemDiagnostics page
- **Atom backend selection**: Added backend_id display to ParameterPanel
- **Backend risks**: Updated ValidationPanel with backend-specific risk categorization

### Changed
- Updated README with Cedalion installation instructions and `backends` command
- Updated test count from 445 to 555 tests

### Technical Details
- Schema version: 0.2.0 → 0.3.0
- New error codes: `BACKEND_BRIDGE_REQUIRED`, `BACKEND_UNAVAILABLE`, `BACKEND_VERSION_MISMATCH`
- New markers: `core`, `full`, `cedalion`, `adapter`, `real_data`

## [1.0.3] - 2026-07-12

### Added

- **Homer3 bidirectional adapter**: Import Homer3 `.cfg`/`.json`/processFunc configs and convert to fnirs-flow atoms (`fnirs_flow/adapters/homer3_import.py`)
- **AnalyzIR bidirectional adapter**: Import AnalyzIR `.R`/`.json` scripts and convert to fnirs-flow atoms (`fnirs_flow/adapters/analyzir_import.py`); export fnirs-flow atoms to AnalyzIR R script (`fnirs_flow/adapters/analyzir_export.py`)
- **CLI adapter commands**: `import-homer3`, `import-analyzir`, `export-homer3`, `export-analyzir` subcommands with full file I/O, summary output, and report generation
- **Cross-backend integration tests**: 94 tests covering Homer3↔AnalyzIR round-trip, triple-chain symmetry, parameter preservation, and CLI end-to-end workflows (`tests/test_homer3_bidirectional.py`, `tests/test_analyzir_bidirectional.py`, `tests/test_cross_backend_integration.py`, `tests/test_cli_adapters.py`)
- **Unified adapter API**: `fnirs_flow/adapters/__init__.py` exports all 16 public functions/classes for Homer3 and AnalyzIR import/export

### Supported mappings (13 atom types ↔ 15 backend functions)

| fnirs-flow Atom | Homer3 Function | AnalyzIR R Function |
|---|---|---|
| `optical_density` | `hmrR_Intensity2OD` | `hmrR_Intensity2OD` |
| `bandpass_filter` | `hmrR_BandpassFilt` | `hmrR_BandpassFilt` |
| `tddr_motion` | `hmrR_MotionCorrectTD` | `hmrR_MotionCorrectTD` |
| `wavelet_motion_correction` | `hmrR_MotionCorrectWavelet` | `hmrR_MotionCorrectWavelet` |
| `spline_motion_correction` | `hmrR_MotionCorrectSpline` | `hmrR_MotionCorrectSpline` |
| `pca_motion_correction` | `hmrR_MotionCorrectPCA` | `hmrR_MotionCorrectPCA` |
| `cbsi_motion_correction` | `hmrR_MotionCorrectCBSI` | `hmrR_MotionCorrectCBSI` |
| `beer_lambert_law` | `hmrR_OD2Conc` | `hmrR_OD2Conc` |
| `scalp_coupling_index` | `hmrR_Sci` | `hmrR_Sci` |
| `short_channel_regression` | `hmrR_StatAvg` | `hmrR_StatAvg` |
| `block_averaging` | `hmrR_BlockAvg` | `hmrR_BlockAvg` |
| `first_level_glm` | `hmrR_GLM` | `hmrR_GLM` |
| `ica_motion_correction` | *(not supported)* | *(not supported)* |

## [1.0.2] - 2026-07-11

### Fixed

- **Code audit fixes**: Resolve all Ruff warnings, Mypy type errors, and npm vulnerabilities
- **Ruff F541**: Remove extraneous `f` prefix from 2 f-strings in `cli.py`
- **Mypy type errors**: Fix 25 type errors across 11 files:
  - `validation/graph.py`: Fix type confusion in cycle detection (FlowAtom vs str)
  - `package_exporter.py`: Add explicit `dict[str, Any]` type for `relink_content`
  - `methodatom_library.py`: Replace `datetime.UTC` with `timezone.utc` for Python 3.10 compatibility
  - `roi_mapping.py`: Add explicit return type annotations for numpy operations
  - `mne_nirs_steps.py`: Add type annotations for PCA/ICA results
  - `service.py`: Add explicit return types for JSON loading functions
  - `batch_adapter.py`: Add return type annotation for `_get_operation`
  - `evidence_config.py`: Add return type annotation for motion correction methods
  - `api/projects.py`: Add return type annotation for `get_flow`
  - `package_importer.py`: Add explicit `dict[str, Any]` type for `import_metadata`
- **npm vulnerabilities**: Upgrade vite to 8.1.4, fixing esbuild security vulnerability (GHSA-67mh-4wv8-2f99)
- **Exception handling**: Refine 6 broad `except Exception` catches to specific exception types:
  - `api/app.py`: `(ValueError, AttributeError)` for CORS validation
  - `execution/service.py`: `(AttributeError, TypeError)` for sfreq access
  - `data/discovery.py`: `(ImportError, OSError, RuntimeError)` for MNE data path
  - `api/projects.py`: `(OSError, KeyError, ValueError, RuntimeError)` for discovery/dryrun/execute
- **Validation bug**: Fix `node` variable name conflict in `validation/graph.py` cycle detection

### Security

- **npm audit**: 0 vulnerabilities (was 2: esbuild moderate, vite high)

### WebUI

- **Fatal validation risk**: Block Execute button when fatal risks detected in validation
  - `store.ts`: Add `hasFatalRisk` to `projectStatus` computed
  - `AppShell.tsx`: Disable Run button when `hasFatalRisk` is true
  - `RunMonitor.tsx`: Disable Execute button when `hasFatalRisk` is true
- **Results Workspace**: New page for browsing execution results
  - `ResultsWorkspace.tsx`: Artifacts table, QC/Channel/ROI/Group tabs
  - Copy-to-clipboard for artifact paths
  - Metrics grid for run statistics
- **Import Package**: New page for importing `.fnirsflow.zip` packages
  - `ImportPackage.tsx`: Package path input, import status display
  - Quarantined atoms list with trust buttons
  - Fork action for read-only packages
  - Reviewer mode banner
- **Export Profile Selector**: Choose export profile before packaging
  - `ExportPackage.tsx`: Profile selection cards (reproducibility/submission/reviewer)
  - Show package contents based on selected profile
  - Display selected profile in export result
- **DAG Layer Preview**: Visual representation of execution DAG
  - `DagLayerPreview.tsx`: Layer-by-layer node visualization
  - Integrated into CompileSummary page
- **Route updates**:
  - `/results` now shows ResultsWorkspace (was CompileSummary)
  - `/compile` added for CompileSummary
  - `/import` added for ImportPackage
- **Navigation**: Add Compile and Import nav items to AppShell
- **API client**: Add `ExportOptions` interface and `importPackage` function

## [1.0.1] - 2026-07-10

### Security

- **CRITICAL**: Replace `raw._data` private attribute mutation with safe `_copy_raw_with_data()` helper in MNE adapter — prevents silent data corruption across MNE versions
- **CRITICAL**: Replace `tempfile.mktemp()` with `tempfile.NamedTemporaryFile(delete=False)` to eliminate TOCTOU race condition
- **HIGH**: Default WebUI server to `127.0.0.1` instead of `0.0.0.0`; add `--host` CLI flag
- **HIGH**: Add input validation on `ProjectCreate.name` — reject empty, oversized, and path-traversal names
- **HIGH**: Sanitize CORS origins via `FNIRS_CORS_ORIGINS` env var; restrict `allow_methods` to specific verbs
- **HIGH**: Add `threading.Lock` to `ProjectStore` for thread-safe async FastAPI usage
- **HIGH**: Auto-clean exported temp files on failure to prevent disk leaks
- **HIGH**: Consolidate security validation — remove duplicate checks across `validate_security`, `validate_node_states`, and `validate_custom_node_safety`; quarantine/capability/checksum checks now live in a single module

### Fixed

- **Flow hash stability**: `compute_flow_hash()` now excludes mutable metadata (timestamps, author, tags) for content-addressed identity
- **Package importer**: Initialize `names` variable before try-block to prevent `UnboundLocalError`
- **CLI**: File existence check before reading flow JSON; return exit code 0 for help display
- **API error handling**: Log exceptions in `discover_project_data`, `dry_run_project`, `export_project_package` instead of silently swallowing
- **Version strings**: Replace 4 hardcoded `"1.0.0"` references with `fnirs_flow.__version__`
- **FlowCanvas stale state**: Replace `useNodesState`/`useEdgesState` initial values with `useEffect` sync to fix React stale state bug
- **ExportPackage false success**: Add try/catch to show errors instead of false success message
- **ParameterPanel NaN**: Guard `parseFloat` against empty input
- **Router priority**: Document `scenario` field as authoritative; boolean flags are backward-compatible fallbacks
- **Pipeline error handling**: `CompositeChain.invoke()` wraps step failures with step name in `RuntimeError`
- **Validation string normalization**: `SensitivityValidator`/`InclusionValidator` now use case-insensitive, whitespace-insensitive matching
- **PhysiologyRegressionStep**: Default strategy now correctly says "no physiology regression available" when no data exists
- **`_version_gte()`**: Tolerate pre-release semver suffixes (e.g., `0.2.0-beta`)
- **`FailureStore.register()`**: Fix `TypeError` by passing keyword arguments instead of `RunContext` object
- **`subjects_with_missing_fields`**: Count unique subjects with `set` instead of `max()` across fields
- **DFS cycle detection**: Report full cycle path (A -> B -> C -> A) instead of just one node
- **`ExecutionDag.model_dump()`**: Add dual-write override to auto-populate `atoms` from `nodes`
- **RiskItem.domain**: Add `"harmonization"` and `"multi_site"` to enum
- **Schema `fnirs_flow.schema.json`**: Add `nodes` to required fields (alongside `edges`)
- **Schema `capability_manifest.schema.json`**: Add `$id` for identification
- **Schema `risk_item.schema.json`**: Add `"harmonization"` and `"multi_site"` to domain enum
- **`open()` encoding**: Add `encoding="utf-8"` to 13 text file operations across the codebase
- **Bare except**: Replace 3 `except Exception` with specific exception types; replace 3 bare `except:` with `(FileNotFoundError, csv.Error)`
- **Unused imports**: Remove `from typing import Any` from 6 files
- **Hardcoded paths**: 2 scripts now use `Path(__file__).resolve().parent.parent` instead of relative paths
- **`demo_full_pipeline.py`**: Remove fragile `sys.path.insert` hack
- **Typo fix**: `NUISTANCE_GLM` → `NUISANCE_GLM` (3 occurrences)
- **`__init__.py` exports**: Add public API re-exports to `fnirs_flow/flow/__init__.py`
- **`_load_all` logging**: Log warning when skipping corrupt project.json files

### Changed

- **pyproject.toml**: Remove unused `jsonschema` core dependency; add `[tool.ruff]` and `[tool.mypy]` configs
- **`fnirs_pipeline/core/__init__.py`**, **`chains/`**, **`steps/`**, **`validators/`**: Add missing `__init__.py` files for proper package discovery
- **CLI test**: Update `test_no_command_returns_1` → `test_no_command_returns_0` to match convention
- **Security tests**: Quarantine tests now use `validate_security` instead of `validate_node_states`
- **`generate_library.py`**: Remove dead `atom_naming` dictionary (166 lines of unused code)

### Removed

- **`webui/src/hooks/useProject.ts`**: Dead code — never imported by any component

### WebUI

- Replace raw `fetch()` with axios client for `handleDryRun`/`handleExport`
- Add `dryRun()` and `exportPackage()` API client functions
- Add request timeout (30s) to axios instance
- Fix `discoverData` to use `params` instead of URL interpolation (prevents URL injection)
- Remove `console.log` debug statement from `handleCompile`
- Make `DataImport` datasets configurable via props
- Fix `h1 onClick` accessibility — use semantic `<button>` element
- Add `Parameter.options` interface for select inputs
