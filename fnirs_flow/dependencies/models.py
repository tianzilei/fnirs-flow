"""Data models for MethodAtom dependency resolution and controlled installation.

Implements the data model from the design document:
  - PackageRequirement: individual package requirement
  - DependencyProfile: backend dependency profile
  - ResolvedRequirement: resolution result for a single requirement
  - EnvironmentAction: action needed to satisfy a dependency
  - DependencyPlan: complete dependency resolution plan
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ============================================================================
# Enums
# ============================================================================


class RequirementStatus(str, Enum):
    """Status of a resolved requirement."""

    SATISFIED = "satisfied"
    MISSING = "missing"
    INCOMPATIBLE_VERSION = "incompatible_version"
    INCOMPATIBLE_PYTHON = "incompatible_python"
    CAPABILITY_MISSING = "capability_missing"
    BROKEN_IMPORT = "broken_import"
    SOURCE_NOT_ALLOWED = "source_not_allowed"
    INTEGRITY_UNVERIFIED = "integrity_unverified"
    PROBE_FAILED = "probe_failed"


class PlanStatus(str, Enum):
    """Status of a dependency plan."""

    UNRESOLVED = "unresolved"
    RESOLVING = "resolving"
    SATISFIED = "satisfied"
    APPROVAL_REQUIRED = "approval_required"
    REJECTED = "rejected"
    APPROVED = "approved"
    INSTALLING = "installing"
    INSTALLED = "installed"
    PROBING = "probing"
    READY_TO_EXECUTE = "ready_to_execute"
    BLOCKED = "blocked"


class EnvironmentActionType(str, Enum):
    """Type of environment action needed."""

    INSTALL_PACKAGE = "install_package"
    CREATE_ENVIRONMENT = "create_environment"
    UPGRADE_PACKAGE = "upgrade_package"
    CHECK_CAPABILITY = "check_capability"


class InstallPolicy(str, Enum):
    """Installation policy."""

    NEVER = "never"
    APPROVED_ONCE = "approved_once"
    PREAUTHORIZED = "preauthorized"


# ============================================================================
# Package and Profile Models
# ============================================================================


class PackageRequirement(BaseModel):
    """Requirement for a single package."""

    distribution: str
    import_name: str
    version_specifier: str
    source: str
    integrity: str | None = None
    optional_for: set[str] = Field(default_factory=set)


class DependencyProfile(BaseModel):
    """Static, trusted backend dependency profile.

    Each profile describes the packages, capabilities, and installation
    requirements for a specific backend version.
    """

    profile_id: str
    backend_id: str
    display_name: str
    python_requires: str
    packages: list[PackageRequirement]
    capabilities: set[str]
    install_source_policy: str
    environment_strategy: str
    probe_module: str
    probe_callable: str | None = None

    def fingerprint(self) -> str:
        """Compute a stable fingerprint for this profile."""
        data = {
            "profile_id": self.profile_id,
            "backend_id": self.backend_id,
            "packages": [
                {
                    "distribution": p.distribution,
                    "version_specifier": p.version_specifier,
                    "source": p.source,
                }
                for p in self.packages
            ],
            "capabilities": sorted(self.capabilities),
        }
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()


# ============================================================================
# Resolution Models
# ============================================================================


class ResolvedRequirement(BaseModel):
    """Result of resolving a single package requirement."""

    package: PackageRequirement
    profile_id: str
    status: RequirementStatus
    installed_version: str | None = None
    python_compatible: bool = True
    capabilities_met: bool = True
    available_capabilities: set[str] = Field(default_factory=set)
    missing_capabilities: set[str] = Field(default_factory=set)
    error_message: str | None = None
    probe_details: dict[str, Any] = Field(default_factory=dict)


class EnvironmentAction(BaseModel):
    """Action needed to satisfy a dependency."""

    action_type: EnvironmentActionType
    profile_id: str
    package: PackageRequirement | None = None
    target_environment: str = ""
    estimated_download_bytes: int | None = None
    description: str = ""


class AffectedAtom(BaseModel):
    """Atom affected by a dependency requirement."""

    atom_id: str
    atom_type: str
    template_id: str | None = None
    required_capabilities: set[str] = Field(default_factory=set)


class DependencyPlan(BaseModel):
    """Complete dependency resolution plan.

    This is the serializable, auditable output of the dependency resolver.
    """

    plan_id: str
    flow_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: PlanStatus = PlanStatus.UNRESOLVED
    requirements: list[ResolvedRequirement] = Field(default_factory=list)
    affected_atoms: dict[str, list[str]] = Field(default_factory=dict)
    environment_actions: list[EnvironmentAction] = Field(default_factory=list)
    requires_user_approval: bool = False
    network_required: bool = False
    estimated_download_bytes: int | None = None
    warnings: list[str] = Field(default_factory=list)
    plan_fingerprint: str = ""

    def compute_fingerprint(self) -> str:
        """Compute plan fingerprint from requirements and affected atoms."""
        data = {
            "flow_id": self.flow_id,
            "requirements": [
                {
                    "profile_id": r.profile_id,
                    "distribution": r.package.distribution,
                    "version_specifier": r.package.version_specifier,
                    "source": r.package.source,
                }
                for r in self.requirements
            ],
            "affected_atoms": self.affected_atoms,
        }
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()

    def is_satisfied(self) -> bool:
        """Check if all requirements are satisfied."""
        return all(r.status == RequirementStatus.SATISFIED for r in self.requirements)

    def blocked_requirements(self) -> list[ResolvedRequirement]:
        """Return requirements that are not satisfied."""
        return [r for r in self.requirements if r.status != RequirementStatus.SATISFIED]

    def summary(self) -> dict[str, Any]:
        """Return a human-readable summary of the plan."""
        status_counts: dict[str, int] = {}
        for r in self.requirements:
            status_counts[r.status.value] = status_counts.get(r.status.value, 0) + 1

        return {
            "plan_id": self.plan_id,
            "flow_id": self.flow_id,
            "status": self.status.value,
            "total_requirements": len(self.requirements),
            "status_counts": status_counts,
            "requires_approval": self.requires_user_approval,
            "network_required": self.network_required,
            "affected_atom_count": sum(len(atoms) for atoms in self.affected_atoms.values()),
            "warning_count": len(self.warnings),
        }

    def format_user_error(self) -> str:
        """Format user-facing error message per §12 of design document.

        §12: 面向用户的错误必须指出"哪个 MethodAtom、缺什么、下一步是什么"

        Example output:
            MethodAtom `atom-od-01` requires Cedalion capability `int2od`.
            Dependency profile `cedalion-26.5` is not installed.
            No download or installation was started.
            Resolve the dependency plan and approve installation, or replace this atom implementation.
        """
        if self.is_satisfied():
            return ""

        lines: list[str] = []

        # Build reverse index: profile_id -> atom_ids
        for profile_id, atom_ids in self.affected_atoms.items():
            # Find blocked requirements for this profile
            blocked = [
                r for r in self.blocked_requirements()
                if r.profile_id == profile_id
            ]

            if not blocked:
                continue

            # Get profile display name
            profile_name = profile_id

            # Format error for each affected atom
            for atom_id in atom_ids[:3]:  # Limit to 3 atoms for readability
                for req in blocked:
                    if req.status == RequirementStatus.MISSING:
                        lines.append(
                            f"MethodAtom `{atom_id}` requires dependency "
                            f"`{req.package.distribution}` from profile `{profile_name}`."
                        )
                    elif req.status == RequirementStatus.INCOMPATIBLE_VERSION:
                        lines.append(
                            f"MethodAtom `{atom_id}` requires `{req.package.distribution}` "
                            f"{req.package.version_specifier}, but {req.installed_version} is installed."
                        )
                    elif req.status == RequirementStatus.INCOMPATIBLE_PYTHON:
                        lines.append(
                            f"MethodAtom `{atom_id}` requires Python compatible with "
                            f"`{profile_name}`, but current Python version is incompatible."
                        )
                    elif req.status == RequirementStatus.CAPABILITY_MISSING:
                        lines.append(
                            f"MethodAtom `{atom_id}` requires capability from "
                            f"`{req.package.distribution}` that is not available."
                        )

            # Summary line
            if blocked:
                status_desc = ", ".join(set(r.status.value for r in blocked))
                lines.append(
                    f"Dependency profile `{profile_name}` status: {status_desc}."
                )

        # Next steps
        if self.requires_user_approval:
            lines.append("")
            lines.append(
                "No download or installation was started. "
                "Resolve the dependency plan and approve installation, "
                "or replace the affected MethodAtom implementations."
            )
        else:
            lines.append("")
            lines.append(
                "Check the dependency plan for details, or replace the affected MethodAtom implementations."
            )

        return "\n".join(lines)


# ============================================================================
# Approval Models
# ============================================================================


class ApprovalRecord(BaseModel):
    """Record of a dependency installation approval."""

    plan_id: str
    plan_fingerprint: str
    decision: InstallPolicy
    approved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    approved_by: str = "local-user"
    allowed_sources: list[str] = Field(default_factory=list)
    target_environment: str = ""


class InstallationTask(BaseModel):
    """Track an installation task."""

    task_id: str
    plan_id: str
    profile_id: str
    status: str = "pending"  # pending, running, completed, failed, cancelled
    started_at: str | None = None
    completed_at: str | None = None
    progress: float = 0.0
    log_lines: list[str] = Field(default_factory=list)
    error: str | None = None


# ============================================================================
# Provenance Models
# ============================================================================


class EnvironmentManifest(BaseModel):
    """Manifest of an environment's state for provenance tracking."""

    python_version: str = ""
    platform: str = ""
    profile_id: str = ""
    direct_dependencies: dict[str, str] = Field(default_factory=dict)
    frozen_dependencies: str = ""
    install_source: str = ""
    install_tag: str = ""
    install_commit: str = ""
    environment_fingerprint: str = ""
    loaded_backend_version: str = ""
    capability_probe_results: dict[str, Any] = Field(default_factory=dict)
    atom_mappings: dict[str, str] = Field(default_factory=dict)
