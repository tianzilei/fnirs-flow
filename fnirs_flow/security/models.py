"""Executable node security models: capability manifest, trust levels, quarantine."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fnirs_flow.flow.atoms import CapabilityManifest, ExecutableTrustLevel

# Re-export for convenience
__all__ = [
    "CapabilityManifest",
    "ExecutableTrustLevel",
    "RuntimeManifest",
    "DependencyManifest",
    "SecurityCheck",
]


class RuntimeManifest(BaseModel):
    python_version: str = ""
    packages: dict[str, str] = Field(default_factory=dict)


class DependencyManifest(BaseModel):
    packages: dict[str, str] = Field(default_factory=dict)


class SecurityCheck(BaseModel):
    name: str
    status: str = Field(pattern="^(pass|warn|fail)$")
    message: str = ""
    risk_id: str = ""
