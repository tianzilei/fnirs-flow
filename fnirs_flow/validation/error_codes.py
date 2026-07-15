"""Typed error codes: canonical error/risk code definitions for the public API contract."""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Typed error codes for validation and execution failures."""

    # Security
    ATOM_COMPAT_VERSION_UNSATISFIED = "atom-compat-version-unsatisfied"
    ATOM_MANIFEST_MISSING = "atom-manifest-missing"
    ATOM_PATH_ESCAPE = "atom-path-escape"
    ATOM_SHELL_FORBIDDEN = "atom-shell-forbidden"

    # Adapter
    ADAPTER_SCHEMA_MISMATCH = "adapter-schema-mismatch"
    ADAPTER_AMBIGUOUS = "adapter-ambiguous"

    # Backend
    BACKEND_BRIDGE_REQUIRED = "backend-bridge-required"
    BACKEND_UNAVAILABLE = "backend-unavailable"
    BACKEND_VERSION_MISMATCH = "backend-version-mismatch"

    # Export
    PACKAGE_PROFILE_UNSUPPORTED = "package-profile-unsupported"

    # Graph
    FLOW_CYCLE_DETECTED = "flow-cycle-detected"

    # Design
    FLOW_MISSING_CONTRASTS = "flow-missing-contrasts"
    FLOW_MISSING_EVENTS = "flow-missing-events"

    # QC
    QC_SCI_BELOW_THRESHOLD = "qc-sci-below-threshold"
    QC_SD_DISTANCE_INVALID = "qc-sd-distance-invalid"
    QC_NO_SHORT_CHANNELS = "qc-no-short-channels"

    # Reproducibility
    REPRODUCIBILITY_NO_SEED = "reproducibility-no-seed"

    # Harmonization
    HARMONIZATION_SITE_MISSING = "harmonization-site-missing"
    HARMONIZATION_SITE_CONFOUNDED = "harmonization-site-confounded"
    HARMONIZATION_INSUFFICIENT_SAMPLES = "harmonization-insufficient-samples"

    # Execution
    EXECUTION_FAILED = "execution-failed"
    EXECUTION_IO_ERROR = "execution-io-error"
    EXECUTION_TIMEOUT = "execution-timeout"
    EXECUTION_VALIDATION_ERROR = "execution-validation-error"


class ErrorSeverity(str, Enum):
    """Severity levels for typed error codes."""

    FATAL = "fatal"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Mapping from ErrorCode to (severity, domain)
ERROR_CODE_MAP: dict[ErrorCode, tuple[ErrorSeverity, str]] = {
    # Security
    ErrorCode.ATOM_COMPAT_VERSION_UNSATISFIED: (ErrorSeverity.FATAL, "security"),
    ErrorCode.ATOM_MANIFEST_MISSING: (ErrorSeverity.FATAL, "security"),
    ErrorCode.ATOM_PATH_ESCAPE: (ErrorSeverity.FATAL, "security"),
    ErrorCode.ATOM_SHELL_FORBIDDEN: (ErrorSeverity.FATAL, "security"),
    # Adapter
    ErrorCode.ADAPTER_SCHEMA_MISMATCH: (ErrorSeverity.HIGH, "adapter"),
    ErrorCode.ADAPTER_AMBIGUOUS: (ErrorSeverity.MEDIUM, "adapter"),
    # Backend
    ErrorCode.BACKEND_BRIDGE_REQUIRED: (ErrorSeverity.FATAL, "backend"),
    ErrorCode.BACKEND_UNAVAILABLE: (ErrorSeverity.FATAL, "backend"),
    ErrorCode.BACKEND_VERSION_MISMATCH: (ErrorSeverity.HIGH, "backend"),
    # Export
    ErrorCode.PACKAGE_PROFILE_UNSUPPORTED: (ErrorSeverity.FATAL, "export"),
    # Graph
    ErrorCode.FLOW_CYCLE_DETECTED: (ErrorSeverity.FATAL, "graph"),
    # Design
    ErrorCode.FLOW_MISSING_CONTRASTS: (ErrorSeverity.MEDIUM, "design"),
    ErrorCode.FLOW_MISSING_EVENTS: (ErrorSeverity.HIGH, "design"),
    # QC
    ErrorCode.QC_SCI_BELOW_THRESHOLD: (ErrorSeverity.MEDIUM, "qc"),
    ErrorCode.QC_SD_DISTANCE_INVALID: (ErrorSeverity.HIGH, "qc"),
    ErrorCode.QC_NO_SHORT_CHANNELS: (ErrorSeverity.MEDIUM, "qc"),
    # Reproducibility
    ErrorCode.REPRODUCIBILITY_NO_SEED: (ErrorSeverity.LOW, "reproducibility"),
    # Harmonization
    ErrorCode.HARMONIZATION_SITE_MISSING: (ErrorSeverity.FATAL, "harmonization"),
    ErrorCode.HARMONIZATION_SITE_CONFOUNDED: (ErrorSeverity.HIGH, "harmonization"),
    ErrorCode.HARMONIZATION_INSUFFICIENT_SAMPLES: (ErrorSeverity.HIGH, "harmonization"),
    # Execution
    ErrorCode.EXECUTION_FAILED: (ErrorSeverity.HIGH, "execution"),
    ErrorCode.EXECUTION_IO_ERROR: (ErrorSeverity.HIGH, "execution"),
    ErrorCode.EXECUTION_TIMEOUT: (ErrorSeverity.HIGH, "execution"),
    ErrorCode.EXECUTION_VALIDATION_ERROR: (ErrorSeverity.MEDIUM, "execution"),
}


def get_error_severity(code: ErrorCode) -> ErrorSeverity:
    """Get the severity for a given error code."""
    return ERROR_CODE_MAP[code][0]


def get_error_domain(code: ErrorCode) -> str:
    """Get the domain for a given error code."""
    return ERROR_CODE_MAP[code][1]


def all_error_codes() -> list[str]:
    """Return all error code string values."""
    return [code.value for code in ErrorCode]
