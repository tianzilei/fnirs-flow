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

Dependency license checks were refreshed during the v1.2.0 release validation.
The direct runtime and optional dependencies declared by
the project include Pydantic, FastAPI, Uvicorn, MNE, MNE-NIRS, MNE-BIDS,
NumPy, SciPy, scikit-learn, PyWavelets, pytest, React, React DOM,
React Router, React Flow, Zustand, Axios, Lucide React, TypeScript, Vite, and
the Vite React plugin. These dependencies are not vendored in this repository
and remain under their upstream licenses.

Release validation found 0 known Python vulnerabilities and 0 npm
vulnerabilities in the checked environments. Detailed audit logs are not part
of the public code tree.

No GPL, AGPL, commercial, or proprietary dependency license was found in these
release environments. The WebUI inventory reports the private root package as
`UNLICENSED`; this is the project itself, not a third-party dependency. The
public release remains governed by the repository `LICENSE`.

## Referenced External Toolboxes and Projects

During development, external projects such as Langflow, LangChain, MNE-Python,
neuroCombat, fMRIPrep, ComBatHarmonization, Homer3, SPM, NIRS-KIT, and
NIRS-SPM were reviewed for engineering, interoperability, or methodological
comparison. They are not vendored, linked into, or redistributed as part of
this public `fnirs-flow` source release.

Projects with GPL, academic-use restricted, Apache-2.0 notice-bearing, or
SPM-dependent terms remain reference-only. Runtime dependencies are installed
from their upstream packages according to the dependency declarations in this
repository.

## Public Release Exclusions

The public release sync intentionally excludes reference repository mirrors,
manuscript drafts, literature extraction workspaces, generated outputs, local
sample data, audit logs, caches, local agent metadata, and legacy non-release
code. The manuscript/submission upload package is maintained separately from
the code-oriented public release repository.
