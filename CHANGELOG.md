# Changelog

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
