"""Static dependency profile registry for known backends.

This module provides trusted, pre-declared dependency profiles for
backends like Cedalion. Profiles are static and do not trigger any
network activity or package imports.
"""

from __future__ import annotations

from fnirs_flow.dependencies.models import DependencyProfile, PackageRequirement


class DependencyProfileRegistry:
    """Registry of trusted dependency profiles.

    Profiles are registered at module load time and are purely static.
    No network activity, no package imports, no environment checks.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, DependencyProfile] = {}

    def register(self, profile: DependencyProfile) -> None:
        """Register a dependency profile."""
        self._profiles[profile.profile_id] = profile

    def get(self, profile_id: str) -> DependencyProfile | None:
        """Get a profile by ID."""
        return self._profiles.get(profile_id)

    def list_all(self) -> list[DependencyProfile]:
        """List all registered profiles."""
        return list(self._profiles.values())

    def list_for_backend(self, backend_id: str) -> list[DependencyProfile]:
        """List profiles for a specific backend."""
        return [p for p in self._profiles.values() if p.backend_id == backend_id]

    def get_by_backend(self, backend_id: str) -> DependencyProfile | None:
        """Get the latest profile for a backend (first registered)."""
        for p in self._profiles.values():
            if p.backend_id == backend_id:
                return p
        return None


# Global registry instance
_registry = DependencyProfileRegistry()


def get_profile_registry() -> DependencyProfileRegistry:
    """Get the global dependency profile registry."""
    return _registry


def register_known_profiles() -> None:
    """Register all known backend dependency profiles.

    This function is called once at module load time. It only registers
    static metadata - no imports, no network, no environment checks.
    """
    # Cedalion 26.5 profile
    cedalion_profile = DependencyProfile(
        profile_id="cedalion-26.5",
        backend_id="cedalion",
        display_name="Cedalion 26.5 backend",
        python_requires=">=3.11,<3.13",
        packages=[
            PackageRequirement(
                distribution="cedalion",
                import_name="cedalion",
                version_specifier="==26.5.1",
                source="git+https://github.com/ibs-lab/cedalion.git@v26.5.1",
                integrity=None,
                optional_for=set(),
            ),
        ],
        capabilities={
            "snirf_read",
            "int2od",
            "od2conc",
            "glm",
            "dot",
            "signal_decomposition",
        },
        install_source_policy="allowlisted_git_tag",
        environment_strategy="isolated_backend_env",
        probe_module="fnirs_flow.adapters.cedalion_capabilities",
    )
    _registry.register(cedalion_profile)

    # MNE-NIRS profile (lightweight, often pre-installed)
    mne_nirs_profile = DependencyProfile(
        profile_id="mne-nirs-1.0",
        backend_id="mne_nirs",
        display_name="MNE-NIRS backend",
        python_requires=">=3.10",
        packages=[
            PackageRequirement(
                distribution="mne",
                import_name="mne",
                version_specifier=">=1.6,<2.0",
                source="pypi://mne",
                integrity=None,
                optional_for=set(),
            ),
            PackageRequirement(
                distribution="mne-nirs",
                import_name="mne_nirs",
                version_specifier=">=0.7,<1.0",
                source="pypi://mne-nirs",
                integrity=None,
                optional_for=set(),
            ),
        ],
        capabilities={
            "snirf_read",
            "optical_density",
            "beer_lambert_law",
            "filtering",
            "motion_correction",
            "block_averaging",
            "glm",
        },
        install_source_policy="pypi",
        environment_strategy="main_environment",
        probe_module="fnirs_flow.adapters.mne_nirs_adapter",
    )
    _registry.register(mne_nirs_profile)


# Register profiles at module load time
register_known_profiles()
