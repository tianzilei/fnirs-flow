"""Dependency provenance tracking.

Records dependency resolution results, installation details,
and environment manifests for reproducibility.
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fnirs_flow.dependencies.models import (
    DependencyPlan,
    EnvironmentManifest,
    InstallationTask,
)


class ProvenanceTracker:
    """Tracks dependency resolution and installation provenance.

    Produces structured output files:
    - dependency_plan.json: resolution results
    - environment_manifest.json: environment state
    - dependency_installation_record.json: installation details
    - backend_probe.json: capability probe results
    """

    def __init__(self, output_dir: Path | str) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_plan(self, plan: DependencyPlan) -> Path:
        """Write dependency plan to JSON."""
        path = self.output_dir / "dependency_plan.json"
        path.write_text(
            json.dumps(plan.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def write_environment_manifest(
        self,
        profile_id: str,
        backend_version: str = "",
        probe_results: dict[str, Any] | None = None,
        atom_mappings: dict[str, str] | None = None,
    ) -> Path:
        """Write environment manifest."""
        manifest = EnvironmentManifest(
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            platform=platform.platform(),
            profile_id=profile_id,
            loaded_backend_version=backend_version,
            capability_probe_results=probe_results or {},
            atom_mappings=atom_mappings or {},
        )

        path = self.output_dir / "environment_manifest.json"
        path.write_text(
            json.dumps(manifest.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def write_installation_record(self, task: InstallationTask) -> Path:
        """Write installation record."""
        path = self.output_dir / "dependency_installation_record.json"
        path.write_text(
            json.dumps(task.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def write_probe_results(
        self,
        backend_id: str,
        probe_results: dict[str, Any],
    ) -> Path:
        """Write backend probe results."""
        data = {
            "backend_id": backend_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "probe_results": probe_results,
        }

        path = self.output_dir / "backend_probe.json"
        path.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def load_plan(self) -> DependencyPlan | None:
        """Load a previously written dependency plan."""
        path = self.output_dir / "dependency_plan.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return DependencyPlan.model_validate(data)

    def load_manifest(self) -> EnvironmentManifest | None:
        """Load a previously written environment manifest."""
        path = self.output_dir / "environment_manifest.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return EnvironmentManifest.model_validate(data)
