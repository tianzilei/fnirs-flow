# Public Release Tree

This directory was generated from the private working repository by
`scripts/sync_public_release.py`.

It contains only the code-oriented public release whitelist for the
submission/public repository:

- Python packages and CLI
- JSON schemas and demo configs
- generative AI FlowGraph drafting guide
- tests
- WebUI source and package metadata
- GitHub Actions verification workflow
- selected public docs/specs
- license and third-party notice files

It intentionally excludes manuscript drafts, literature extraction materials,
sample data, generated outputs, reference repositories, caches, and local
platform metadata. The submission manuscript package is handled separately and
is not copied by this script.
