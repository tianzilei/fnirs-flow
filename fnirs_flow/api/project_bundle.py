"""Deprecated project-bundle imports; use ``infrastructure.project_bundle``."""

from fnirs_flow.infrastructure.project_bundle import (
    BUNDLE_MANIFEST,
    BUNDLE_SCHEMA_VERSION,
    BUNDLE_SUFFIX,
    MAX_BUNDLE_BYTES,
    MAX_BUNDLE_FILES,
    MAX_BUNDLE_MANIFEST_BYTES,
    MAX_BUNDLE_UNCOMPRESSED_BYTES,
    MAX_COMPRESSION_RATIO,
    MAX_MEMBER_BYTES,
    MAX_PROJECT_METADATA_BYTES,
    ProjectBundleError,
    ProjectBundleManager,
)

__all__ = [
    "BUNDLE_MANIFEST",
    "BUNDLE_SCHEMA_VERSION",
    "BUNDLE_SUFFIX",
    "MAX_BUNDLE_BYTES",
    "MAX_BUNDLE_FILES",
    "MAX_BUNDLE_MANIFEST_BYTES",
    "MAX_BUNDLE_UNCOMPRESSED_BYTES",
    "MAX_COMPRESSION_RATIO",
    "MAX_MEMBER_BYTES",
    "MAX_PROJECT_METADATA_BYTES",
    "ProjectBundleError",
    "ProjectBundleManager",
]
