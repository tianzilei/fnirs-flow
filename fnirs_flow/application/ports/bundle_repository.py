"""Bundle/package persistence port."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class BundleRepository(Protocol):
    def export(self, project_id: str, destination: Path, *, profile_id: str) -> Path: ...
