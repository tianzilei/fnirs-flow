"""Provenance logger: records parameters, versions, and design anchors."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sanitize_for_json(obj: Any, project_root: Path | None = None) -> Any:
    """Convert non-serializable objects to strings for JSON output."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v, project_root) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v, project_root) for v in obj]
    if isinstance(obj, str) and project_root is not None:
        candidate = Path(obj)
        if candidate.is_absolute():
            try:
                relative = candidate.resolve().relative_to(project_root.resolve())
            except (OSError, ValueError):
                return candidate.name
            else:
                from fnirs_flow.infrastructure.uri import create_project_uri

                return str(create_project_uri(f"outputs/{relative.as_posix()}"))
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


class ProvenanceRecord:
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._commit_id: str = ""
        self._snapshot_id: str = ""

    def set_design_anchor(self, *, commit_id: str = "", snapshot_id: str = "") -> None:
        """Set the design history anchor for all subsequent records."""
        self._commit_id = commit_id
        self._snapshot_id = snapshot_id

    def log(
        self,
        step_id: str,
        parameters: dict[str, Any],
        **legacy_fields: Any,
    ) -> None:
        record: dict[str, Any] = {
            "step_id": step_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parameters": parameters,
            "python_version": sys.version,
        }
        if self._commit_id:
            record["commit_id"] = self._commit_id
        if self._snapshot_id:
            record["snapshot_id"] = self._snapshot_id
        self._records.append(record)

    def all(self) -> list[dict[str, Any]]:
        return list(self._records)

    def extend(self, records: list[dict[str, Any]]) -> None:
        self._records.extend(records)

    def write(self, outdir: Path, *, project_root: Path | None = None) -> Path:
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / "provenance_log.json"
        safe_records = _sanitize_for_json(self._records, project_root)
        path.write_text(json.dumps(safe_records, indent=2), encoding="utf-8")
        return path
