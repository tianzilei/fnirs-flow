"""Read-only dependency resolver for MethodAtom execution DAGs.

This resolver:
  - Reads static dependency profiles and DAG metadata
  - Checks package availability using importlib (no imports)
  - Validates Python version compatibility
  - Generates a DependencyPlan with structured status
  - Never triggers network activity or package installation
  - Never imports large scientific backends
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
from typing import Any

from fnirs_flow.dependencies.models import (
    DependencyPlan,
    EnvironmentAction,
    EnvironmentActionType,
    PackageRequirement,
    PlanStatus,
    RequirementStatus,
    ResolvedRequirement,
)
from fnirs_flow.execution.dag_payload import execution_atoms
from fnirs_flow.registry.dependency_profiles import (
    DependencyProfileRegistry,
    get_profile_registry,
)


class DependencyResolver:
    """Read-only dependency resolver.

    Resolves dependencies for a compiled execution DAG without triggering
    any network activity, package installation, or backend imports.
    """

    def __init__(
        self,
        profile_registry: DependencyProfileRegistry | None = None,
    ) -> None:
        self._profiles = profile_registry or get_profile_registry()

    def resolve(
        self,
        dag: dict[str, Any],
        flow_id: str = "",
    ) -> DependencyPlan:
        """Resolve dependencies for an execution DAG.

        Args:
            dag: The execution_dag.json content
            flow_id: Optional flow identifier

        Returns:
            DependencyPlan with resolution results
        """
        plan = DependencyPlan(
            plan_id=f"depplan-{flow_id or 'unknown'}",
            flow_id=flow_id,
            status=PlanStatus.RESOLVING,
        )

        # Collect atoms and their dependency requirements
        atoms_list = execution_atoms(dag)
        requirements_by_profile: dict[str, list[PackageRequirement]] = {}
        affected_atoms: dict[str, list[str]] = {}  # profile_id -> [atom_ids]

        for atom in atoms_list:
            atom_id = atom.get("atom_id", "")
            backend_id = atom.get("backend_id")

            if not backend_id:
                continue

            # Find the dependency profile for this backend
            profile = self._profiles.get_by_backend(backend_id)
            if profile is None:
                plan.warnings.append(
                    f"No dependency profile found for backend '{backend_id}' "
                    f"(atom '{atom_id}')"
                )
                continue

            # Track affected atoms
            if profile.profile_id not in affected_atoms:
                affected_atoms[profile.profile_id] = []
                requirements_by_profile[profile.profile_id] = []

            affected_atoms[profile.profile_id].append(atom_id)
            requirements_by_profile[profile.profile_id].extend(profile.packages)

        # Deduplicate requirements per profile
        resolved_requirements: list[ResolvedRequirement] = []
        environment_actions: list[EnvironmentAction] = []

        for profile_id, packages in requirements_by_profile.items():
            profile = self._profiles.get(profile_id)
            if profile is None:
                continue

            # Deduplicate packages
            seen_distributions: set[str] = set()
            for package in packages:
                if package.distribution in seen_distributions:
                    continue
                seen_distributions.add(package.distribution)

                # Resolve this single requirement
                resolved = self._resolve_package(package, profile)
                resolved_requirements.append(resolved)

                # Generate environment action if not satisfied
                if resolved.status != RequirementStatus.SATISFIED:
                    action = self._create_environment_action(package, profile, resolved)
                    environment_actions.append(action)

        # Build affected atoms mapping
        affected_atoms_str: dict[str, list[str]] = {
            profile_id: atom_ids
            for profile_id, atom_ids in affected_atoms.items()
        }

        # Determine plan status
        all_satisfied = all(
            r.status == RequirementStatus.SATISFIED for r in resolved_requirements
        )
        requires_approval = not all_satisfied and len(environment_actions) > 0
        network_required = any(
            a.action_type == EnvironmentActionType.INSTALL_PACKAGE
            for a in environment_actions
        )

        plan.requirements = resolved_requirements
        plan.affected_atoms = affected_atoms_str
        plan.environment_actions = environment_actions
        plan.requires_user_approval = requires_approval
        plan.network_required = network_required
        plan.status = PlanStatus.SATISFIED if all_satisfied else PlanStatus.APPROVAL_REQUIRED
        return plan

    def _resolve_package(
        self,
        package: PackageRequirement,
        profile: Any,
    ) -> ResolvedRequirement:
        """Resolve a single package requirement.

        Uses importlib.metadata and importlib.util only - no actual imports.
        """
        result = ResolvedRequirement(
            package=package,
            profile_id=profile.profile_id,
            status=RequirementStatus.SATISFIED,
        )

        # Check Python version compatibility
        if not self._check_python_version(profile.python_requires):
            result.status = RequirementStatus.INCOMPATIBLE_PYTHON
            result.python_compatible = False
            result.error_message = (
                f"Python {sys.version} does not satisfy {profile.python_requires}"
            )
            return result

        # Check if distribution is installed
        try:
            version = importlib.metadata.version(package.distribution)
            result.installed_version = version

            # Check version specifier
            if not self._check_version_match(version, package.version_specifier):
                result.status = RequirementStatus.INCOMPATIBLE_VERSION
                result.error_message = (
                    f"Installed version {version} does not match "
                    f"{package.version_specifier}"
                )
                return result

        except importlib.metadata.PackageNotFoundError:
            result.status = RequirementStatus.MISSING
            result.installed_version = None
            result.error_message = (
                f"Package '{package.distribution}' is not installed"
            )
            return result

        # Check if import entry point exists
        spec = importlib.util.find_spec(package.import_name)
        if spec is None:
            result.status = RequirementStatus.BROKEN_IMPORT
            result.error_message = (
                f"Package '{package.distribution}' is installed but "
                f"import '{package.import_name}' not found"
            )
            return result

        return result

    def _check_python_version(self, python_requires: str) -> bool:
        """Check if current Python version satisfies the requirement."""
        if not python_requires:
            return True

        current = sys.version_info
        # Simple parsing for common specifiers like ">=3.11,<3.13"
        for spec in python_requires.split(","):
            spec = spec.strip()
            if spec.startswith(">="):
                min_ver = tuple(int(x) for x in spec[2:].strip().split("."))
                if current[:len(min_ver)] < min_ver:
                    return False
            elif spec.startswith("<="):
                max_ver = tuple(int(x) for x in spec[2:].strip().split("."))
                if current[:len(max_ver)] > max_ver:
                    return False
            elif spec.startswith("<"):
                max_ver = tuple(int(x) for x in spec[1:].strip().split("."))
                if current[:len(max_ver)] >= max_ver:
                    return False
            elif spec.startswith(">"):
                min_ver = tuple(int(x) for x in spec[1:].strip().split("."))
                if current[:len(min_ver)] <= min_ver:
                    return False
            elif spec.startswith("=="):
                exact = tuple(int(x) for x in spec[2:].strip().split("."))
                if current[:len(exact)] != exact:
                    return False
        return True

    def _check_version_match(self, installed: str, specifier: str) -> bool:
        """Check if installed version matches the specifier.

        Simple implementation for common specifier patterns.
        """
        if not specifier or specifier == "*":
            return True

        try:
            installed_parts = tuple(int(x) for x in installed.split("."))

            for spec in specifier.split(","):
                spec = spec.strip()
                if spec.startswith("=="):
                    required = tuple(int(x) for x in spec[2:].strip().split("."))
                    if installed_parts[:len(required)] != required:
                        return False
                elif spec.startswith(">="):
                    required = tuple(int(x) for x in spec[2:].strip().split("."))
                    if installed_parts[:len(required)] < required:
                        return False
                elif spec.startswith("<"):
                    required = tuple(int(x) for x in spec[1:].strip().split("."))
                    if installed_parts[:len(required)] >= required:
                        return False
                elif spec.startswith(">"):
                    required = tuple(int(x) for x in spec[1:].strip().split("."))
                    if installed_parts[:len(required)] <= required:
                        return False

            return True
        except (ValueError, IndexError):
            # If we can't parse, assume incompatible (fail closed)
            return False

    def _create_environment_action(
        self,
        package: PackageRequirement,
        profile: Any,
        resolved: ResolvedRequirement,
    ) -> EnvironmentAction:
        """Create an environment action for an unsatisfied requirement."""
        if resolved.status == RequirementStatus.MISSING:
            action_type = EnvironmentActionType.INSTALL_PACKAGE
            description = f"Install {package.distribution} {package.version_specifier}"
        elif resolved.status == RequirementStatus.INCOMPATIBLE_VERSION:
            action_type = EnvironmentActionType.UPGRADE_PACKAGE
            description = (
                f"Upgrade {package.distribution} from {resolved.installed_version} "
                f"to {package.version_specifier}"
            )
        else:
            action_type = EnvironmentActionType.CHECK_CAPABILITY
            description = f"Check {package.distribution} capabilities"

        return EnvironmentAction(
            action_type=action_type,
            profile_id=profile.profile_id,
            package=package,
            target_environment=profile.environment_strategy,
            description=description,
        )


def resolve_dependencies(
    dag: dict[str, Any],
    flow_id: str = "",
    profile_registry: DependencyProfileRegistry | None = None,
) -> DependencyPlan:
    """Convenience function to resolve dependencies for a DAG.

    Args:
        dag: The execution_dag.json content
        flow_id: Optional flow identifier
        profile_registry: Optional profile registry (uses global if None)

    Returns:
        DependencyPlan with resolution results
    """
    resolver = DependencyResolver(profile_registry)
    return resolver.resolve(dag, flow_id)
