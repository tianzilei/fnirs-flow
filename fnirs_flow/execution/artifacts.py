"""Artifact store: tracks and registers execution artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class ArtifactRecord(BaseModel):
    artifact_id: str
    subject: str = ""
    session: str = ""
    task: str = ""
    run: str = ""
    step_id: str = ""
    artifact_type: str = ""
    uri: str = ""
    path: str = ""
    sha256: str = ""
    created_at: str = ""


class ArtifactManifest(BaseModel):
    schema_version: str = "0.1.0"
    run_id: str = ""
    artifacts: list[ArtifactRecord] = Field(default_factory=list)


class ArtifactStore:
    def __init__(self) -> None:
        self._artifacts: list[ArtifactRecord] = []

    def register(self, artifact: ArtifactRecord) -> None:
        self._artifacts.append(artifact)

    def all(self) -> list[ArtifactRecord]:
        return list(self._artifacts)

    def to_manifest(self, run_id: str = "") -> ArtifactManifest:
        return ArtifactManifest(
            run_id=run_id,
            artifacts=self._artifacts,
        )


def write_artifact_manifest(manifest: ArtifactManifest, outdir: Path) -> Path:
    """Write a portable artifact manifest without machine-local resolved paths."""
    path = outdir / "artifact_manifest.json"
    path.write_text(json.dumps(manifest.model_dump(), indent=2), encoding="utf-8")
    return path
