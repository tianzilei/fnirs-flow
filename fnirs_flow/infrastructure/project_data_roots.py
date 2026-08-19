"""Machine-local project data root persistence."""

from __future__ import annotations

import json
from pathlib import Path


class ProjectDataRootStore:
    """Persist local data roots outside portable project bundles."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = Path(base_dir)
        self._roots_file = self._base_dir / "project_data_roots.json"
        self._roots: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._roots_file.exists():
            return
        try:
            data = json.loads(self._roots_file.read_text(encoding="utf-8"))
            roots = data.get("roots", {})
            if isinstance(roots, dict):
                self._roots = {str(key): str(value) for key, value in roots.items()}
        except (json.JSONDecodeError, OSError):
            self._roots = {}

    def _save(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._roots_file.write_text(
            json.dumps({"version": "1.0.0", "roots": self._roots}, indent=2), encoding="utf-8"
        )

    def set(self, project_id: str, data_root: str) -> None:
        clean_root = data_root.strip()
        if clean_root:
            self._roots[project_id] = clean_root
        else:
            self._roots.pop(project_id, None)
        self._save()

    def get(self, project_id: str) -> str:
        return self._roots.get(project_id, "")
