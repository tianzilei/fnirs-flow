"""Provenance logger: records parameters, versions, and artifact hashes."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sanitize_for_json(obj: Any) -> Any:
    """Convert non-serializable objects to strings for JSON output."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


class ProvenanceRecord:
    def __init__(self):
        self._records: list[dict[str, Any]] = []

    def log(
        self,
        step_id: str,
        parameters: dict[str, Any],
        input_hashes: dict[str, str] | None = None,
        output_hashes: dict[str, str] | None = None,
    ) -> None:
        self._records.append(
            {
                "step_id": step_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "parameters": parameters,
                "input_hashes": input_hashes or {},
                "output_hashes": output_hashes or {},
                "python_version": sys.version,
            }
        )

    def all(self) -> list[dict[str, Any]]:
        return list(self._records)

    def extend(self, records: list[dict[str, Any]]) -> None:
        self._records.extend(records)

    def write(self, outdir: Path) -> Path:
        path = outdir / "provenance_log.json"
        safe_records = _sanitize_for_json(self._records)
        path.write_text(json.dumps(safe_records, indent=2), encoding="utf-8")
        return path
