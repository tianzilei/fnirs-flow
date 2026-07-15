"""Dependency resolution and controlled installation for MethodAtoms.

This package implements the dependency management system described in
methodatom_dependency_resolution_and_controlled_installation.md.

Key components:
  - models: Data models for DependencyProfile, DependencyPlan, etc.
  - resolver: Read-only dependency resolution
  - policies: Installation policies and source allowlists
  - environment_manager: Isolated environment management
  - installer: Controlled installation tasks
  - probes: Capability probing
  - provenance: Dependency provenance tracking
"""

from fnirs_flow.dependencies.models import (
    DependencyPlan,
    DependencyProfile,
    EnvironmentAction,
    PackageRequirement,
    PlanStatus,
    RequirementStatus,
    ResolvedRequirement,
)

__all__ = [
    "DependencyPlan",
    "DependencyProfile",
    "EnvironmentAction",
    "PackageRequirement",
    "PlanStatus",
    "ResolvedRequirement",
    "RequirementStatus",
]
