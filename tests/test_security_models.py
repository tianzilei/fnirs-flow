"""Tests for security models: capability manifest, trust levels."""

from __future__ import annotations

from fnirs_flow.security.models import (
    CapabilityManifest,
    DependencyManifest,
    ExecutableTrustLevel,
    RuntimeManifest,
    SecurityCheck,
)


class TestExecutableTrustLevel:
    def test_levels(self):
        assert ExecutableTrustLevel.BUILTIN_MANAGED == "builtin_managed"
        assert ExecutableTrustLevel.IMPORTED_CUSTOM == "imported_custom"

    def test_all_levels_covered(self):
        levels = list(ExecutableTrustLevel)
        assert len(levels) >= 4
        # Ensure the core trust levels exist
        assert ExecutableTrustLevel.BUILTIN_MANAGED in levels
        assert ExecutableTrustLevel.IMPORTED_CUSTOM in levels


class TestCapabilityManifest:
    def test_default_manifest(self):
        cap = CapabilityManifest()
        assert not cap.network
        assert not cap.shell
        assert cap.allowed_operations == []

    def test_manifest_with_values(self):
        cap = CapabilityManifest(
            allowed_operations=["read", "filter"],
            file_access=["data/*.snirf"],
            network=False,
            dependencies=["mne>=1.6"],
            checksum="sha256:abc",
        )
        assert len(cap.allowed_operations) == 2
        assert not cap.network


class TestSecurityCheck:
    def test_pass_check(self):
        check = SecurityCheck(name="no_network", status="pass")
        assert check.status == "pass"

    def test_fail_check(self):
        check = SecurityCheck(
            name="no_shell",
            status="fail",
            message="Shell access detected",
            risk_id="risk-001",
        )
        assert check.status == "fail"
        assert check.risk_id == "risk-001"


class TestRuntimeManifest:
    def test_runtime(self):
        rm = RuntimeManifest(python_version="3.13.9", packages={"mne": "1.6.0"})
        assert rm.python_version == "3.13.9"


class TestDependencyManifest:
    def test_deps(self):
        dm = DependencyManifest(packages={"pydantic": ">=2.0"})
        assert "pydantic" in dm.packages
