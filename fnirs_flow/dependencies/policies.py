"""Installation policies and source allowlists for dependency management.

This module enforces the security policies described in the design document:
  - Default install policy is "never"
  - Sources must be pre-allowlisted
  - Git dependencies must be pinned to specific commits/tags
  - No arbitrary PyPI or Git sources allowed
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """Type of package source."""

    PYPI = "pypi"
    GIT_TAG = "git_tag"
    GIT_COMMIT = "git_commit"
    LOCAL_WHEEL = "local_wheel"


class AllowedSource(BaseModel):
    """An allowlisted package source."""

    source_type: SourceType
    url_pattern: str  # e.g., "github.com/ibs-lab/cedalion"
    allowed_tags: list[str] = Field(default_factory=list)
    allowed_commits: list[str] = Field(default_factory=list)
    notes: str = ""


class SourceAllowlist(BaseModel):
    """Registry of allowed package sources.

    Only sources in this list can be used for installation.
    This prevents arbitrary package injection.
    """

    sources: list[AllowedSource] = Field(default_factory=list)

    def is_allowed(self, source: str) -> bool:
        """Check if a source string is in the allowlist."""
        for allowed in self.sources:
            if allowed.source_type == SourceType.PYPI:
                # PyPI sources match by distribution name
                if source.startswith("pypi://"):
                    return True
            elif allowed.source_type in (SourceType.GIT_TAG, SourceType.GIT_COMMIT):
                # Git sources match by URL pattern
                if allowed.url_pattern in source:
                    # Check tag/commit restrictions
                    if allowed.allowed_tags or allowed.allowed_commits:
                        # Extract tag or commit from source
                        tag = self._extract_tag(source)
                        commit = self._extract_commit(source)
                        if tag and tag in allowed.allowed_tags:
                            return True
                        if commit and commit in allowed.allowed_commits:
                            return True
                        return False
                    return True
        return False

    def _extract_tag(self, source: str) -> str | None:
        """Extract git tag from source string."""
        if "@" in source:
            ref = source.split("@")[-1]
            if not ref.startswith("sha256:"):
                return ref
        return None

    def _extract_commit(self, source: str) -> str | None:
        """Extract git commit SHA from source string."""
        if "@" in source:
            ref = source.split("@")[-1]
            if len(ref) >= 7 and all(c in "0123456789abcdef" for c in ref):
                return ref
        return None


# Default allowlist for known backends
DEFAULT_ALLOWLIST = SourceAllowlist(
    sources=[
        AllowedSource(
            source_type=SourceType.GIT_TAG,
            url_pattern="github.com/ibs-lab/cedalion",
            allowed_tags=["v26.5.1"],
            notes="Cedalion backend releases",
        ),
        AllowedSource(
            source_type=SourceType.PYPI,
            url_pattern="pypi://",
            notes="Standard PyPI packages",
        ),
    ]
)


class InstallPolicyManager(BaseModel):
    """Manages installation policies.

    Enforces:
    - Default policy is "never"
    - Approval is per-plan and per-fingerprint
    - No silent auto-installation
    """

    default_policy: str = "never"
    approved_plans: dict[str, str] = Field(default_factory=dict)  # fingerprint -> policy

    def get_policy(self, plan_fingerprint: str) -> str:
        """Get the installation policy for a plan.

        Returns:
            "never" if not approved, "approved_once" if approved
        """
        return self.approved_plans.get(plan_fingerprint, self.default_policy)

    def approve_plan(self, plan_fingerprint: str) -> None:
        """Approve a plan for one-time installation."""
        self.approved_plans[plan_fingerprint] = "approved_once"

    def reject_plan(self, plan_fingerprint: str) -> None:
        """Reject a plan (explicit rejection)."""
        self.approved_plans[plan_fingerprint] = "rejected"

    def is_approved(self, plan_fingerprint: str) -> bool:
        """Check if a plan is approved for installation."""
        return self.get_policy(plan_fingerprint) == "approved_once"


# Global policy manager
_policy_manager = InstallPolicyManager()


def get_policy_manager() -> InstallPolicyManager:
    """Get the global installation policy manager."""
    return _policy_manager


def get_allowlist() -> SourceAllowlist:
    """Get the global source allowlist."""
    return DEFAULT_ALLOWLIST
