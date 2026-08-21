"""Compiled execution plan, DAG, and run resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from fnirs_flow.execution.engine import RunContext, _build_run_id, normalize_entity_labels
from fnirs_flow.execution.models import ExecutionRequest
from fnirs_flow.infrastructure.uri import ProjectURI


def load_plan(compiled_dir: Path) -> dict[str, Any]:
    path = compiled_dir / "plan.json"
    if not path.exists():
        raise FileNotFoundError(f"plan.json not found in {compiled_dir}")
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def load_dag(compiled_dir: Path) -> dict[str, Any]:
    path = compiled_dir / "execution_dag.json"
    if not path.exists():
        raise FileNotFoundError(f"execution_dag.json not found in {compiled_dir}")
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def resolve_runs(compiled_dir: Path, request: ExecutionRequest) -> list[RunContext]:
    manifest_path = compiled_dir / "data_manifest.json"
    if not manifest_path.exists():
        manifest_path = compiled_dir.parent / "data_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"data_manifest.json not found in {compiled_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root_value = request.data_root or manifest.get("local_root", "")
    data_root = Path(root_value).resolve() if root_value else None
    runs: list[RunContext] = []
    seen_run_ids: set[str] = set()

    def resolve_data_path(value: str, relative_path: str = "") -> str:
        if value.startswith("external-data://"):
            try:
                uri = ProjectURI(value)
            except ValueError:
                return ""
            if data_root is not None:
                candidate = data_root / Path(*uri.path.parts)
                return str(candidate) if candidate.exists() else ""
            return ""
        if data_root is not None and relative_path:
            candidate = data_root / relative_path
            if candidate.exists():
                return str(candidate)
        if value and Path(value).exists():
            return str(Path(value))
        return ""

    filters = {
        "subject": normalize_entity_labels("subject", request.participant_labels),
        "session": normalize_entity_labels("session", request.session_labels),
        "task": normalize_entity_labels("task", request.task_labels),
        "run": normalize_entity_labels("run", request.run_labels),
    }
    for subject_run in manifest.get("subject_session_runs", []):
        if any(labels and subject_run.get(field) not in labels for field, labels in filters.items()):
            continue
        relative_path = str(subject_run.get("relative_path", ""))
        runs.append(
            RunContext(
                run_id=_build_run_id(subject_run, _seen=seen_run_ids),
                subject=subject_run.get("subject", ""),
                session=subject_run.get("session", ""),
                run=subject_run.get("run", ""),
                task=subject_run.get("task", ""),
                data_path=resolve_data_path(
                    str(subject_run.get("uri") or subject_run.get("path", "")), relative_path
                ),
                relative_path=relative_path,
                size_bytes=int(subject_run.get("size_bytes", 0)),
                modified_at=str(subject_run.get("modified_at", "")),
                events_path=resolve_data_path(
                    str(subject_run.get("events_uri") or subject_run.get("events_path", ""))
                ),
                status="pending",
            )
        )
    if not runs:
        raise ValueError("No data runs matched the execution request")
    return runs
