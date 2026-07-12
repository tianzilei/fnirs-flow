# Third-Party Notices

This file records third-party dependency and reference boundaries for the
public `fnirs-flow` release.

## Project License

`fnirs-flow` is released under the MIT License. See `LICENSE`.

Copyright holder:

- Zilei Tian

## Runtime and Development Dependencies

The public release depends on third-party packages listed in `pyproject.toml`,
`environment.yml`, and `webui/package.json`. Those packages remain governed by
their own licenses.

Dependency license checks should be generated from the release environment
before publication. The direct runtime and optional dependencies declared by
the project include Pydantic, FastAPI, Uvicorn, MNE, MNE-NIRS, MNE-BIDS,
NumPy, SciPy, scikit-learn, PyWavelets, pytest, React, React DOM,
React Router, React Flow, Zustand, Axios, Lucide React, TypeScript, Vite, and
the Vite React plugin. These dependencies are not vendored in this repository
and remain under their upstream licenses.

Release-time checks still required:

- Confirm Python dependency licenses from the locked release environment.
- Confirm WebUI dependency licenses from `webui/package-lock.json`.
- Add the public release tag and archived source DOI after publication.

## Referenced External Toolboxes and Repositories

The private development repository may contain local reference repositories,
literature extraction materials, manuscript drafts, sample data, generated
outputs, or other non-release artifacts. These are not redistributed in the
public `fnirs-flow` release.

Reference-only materials include:

| Local reference path | License identified from local files | Public-release treatment |
| --- | --- | --- |
| `References/langflow/` | MIT License (`LICENSE`) | Engineering reference only; not vendored or redistributed. |
| `References/langchain/` | MIT License (`LICENSE`) | Engineering reference only; not vendored or redistributed. |
| `References/mne-python/` | BSD 3-Clause style license (`LICENSE.txt`) | Runtime/adapter ecosystem reference; dependency is installed from upstream packages, not vendored. |
| `References/neuroCombat/` | MIT License (`LICENSE`) | Methodological reference only; not vendored or redistributed. |
| `References/fmriprep/` | Apache License 2.0 (`LICENSE`) with `NOTICE` file | Architecture/reproducibility reference only; not vendored or redistributed. |
| `References/ComBatHarmonization/` | MIT License in `Matlab/LICENSE` | Methodological reference only; not vendored or redistributed. |
| `References/Homer3/` | BSD-style Homer3 license (`LICENSE.txt`) | Interoperability/method comparison reference only; not vendored or redistributed. |
| `References/spm/` | GNU GPL version 2 (`LICENCE`) | GPL reference only; not copied into, linked into, or redistributed with `fnirs-flow`. |
| `References/NIRS-KIT/` | GPL version 3 indicated by `LICENSE` and README; additional academic-use terms appear in `LICENCE` | GPL/academic-use reference only; not copied into, linked into, or redistributed with `fnirs-flow`. |
| `References/NIRS_SPM_v4_r1/` | No standalone top-level license file found in the local copy; source files include SPM-dependent/modified SPM routines | SPM-dependent reference only; not copied into, linked into, or redistributed with `fnirs-flow`. |

GPL-licensed, academic-use restricted, Apache-2.0 notice-bearing, or
SPM-dependent reference projects are used only for methodological comparison,
compatibility checking, or interoperability review. They are not copied into,
linked into, or redistributed as part of the `fnirs-flow` source release by
`scripts/sync_public_release.py`.

## Public Release Exclusions

The public release sync intentionally excludes:

- `References/`
- `docs/manuscript/`
- `docs/literature/`
- `outputs/`
- `Sample/`
- `audit/`
- `.tmp/`
- `.agents/`
- `.mimocode/`
- `legacy/`

The manuscript/submission upload package is maintained separately from the
code-oriented public release repository.
