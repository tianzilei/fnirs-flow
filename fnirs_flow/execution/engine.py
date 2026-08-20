"""Execution engine: runs plans without executing real algorithms (dry-run).

Supports derivatives-style output layout and structured ActionAttempt tracking.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from fnirs_flow.execution.dag_payload import execution_atoms


class RunContext(BaseModel):
    run_id: str
    subject: str = ""
    session: str = ""
    run: str = ""
    task: str = ""
    data_path: str = ""
    relative_path: str = ""
    size_bytes: int = 0
    modified_at: str = ""
    source_file_role: str = ""
    events_path: str = ""
    status: str = "pending"
    planned_steps: list[str] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    failed_step: str = ""
    skipped_steps: list[str] = Field(default_factory=list)
    # Deprecated compatibility field. Dry-run never completes real steps.
    steps_completed: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""


class DryRunResult(BaseModel):
    total_runs: int = 0
    planned_runs: list[RunContext] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


def ensure_derivatives_layout(outdir: Path) -> dict[str, Path]:
    """Create derivatives-style directory structure.

    Returns a dict of named directories for use by callers.

    Layout:
        outdir/
        ├── compiled/        # plan.json, execution_dag.json, manifests
        ├── work/            # intermediate working files
        ├── derivatives/     # per-run outputs
        │   ├── reports/     # run-level reportlets
        │   └── group/       # group-level summaries
        ├── logs/            # run_history.jsonl, failure_manifest
        └── export/          # exported packages
    """
    dirs = {
        "compiled": outdir / "compiled",
        "work": outdir / "work",
        "derivatives": outdir / "derivatives",
        "reports": outdir / "derivatives" / "reports",
        "channel": outdir / "derivatives" / "channel",
        "roi": outdir / "derivatives" / "roi",
        "group": outdir / "derivatives" / "group",
        "logs": outdir / "logs",
        "export": outdir / "export",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def _build_run_id(sr: dict[str, Any], _seen: set[str] | None = None) -> str:
    """Build a stable run id from available BIDS entities.

    Appends an explicit sequence suffix if the BIDS-based ID would collide
    with a previously generated ID in the same batch.
    """
    parts = []
    if sr.get("subject"):
        parts.append(f"sub-{sr['subject']}")
    if sr.get("session"):
        parts.append(f"ses-{sr['session']}")
    if sr.get("task"):
        parts.append(f"task-{sr['task']}")
    if sr.get("run"):
        parts.append(f"run-{sr['run']}")

    if parts:
        run_id = "_".join(parts)
    else:
        run_id = "run-unlabeled"

    # Deduplicate within a batch
    if _seen is not None:
        if run_id in _seen:
            base = run_id
            sequence = 2
            while run_id in _seen:
                run_id = f"{base}_{sequence}"
                sequence += 1
        _seen.add(run_id)

    return run_id


def dry_run(
    plan_dir: str | Path,
    data_manifest_path: str | Path | None = None,
    outdir: str | Path | None = None,
    *,
    participant_labels: list[str] | None = None,
    session_labels: list[str] | None = None,
    task_labels: list[str] | None = None,
    run_labels: list[str] | None = None,
) -> DryRunResult:
    """Execute a dry-run: enumerate planned runs without running algorithms.

    Reads execution_dag.json and data_manifest.json from ``plan_dir/compiled/``
    (derivatives-style layout). If outdir is provided, writes run_report.md and
    run_report.json to ``outdir/derivatives/reports/``.
    """
    plan_dir = Path(plan_dir)
    compiled_dir = plan_dir / "compiled"

    # Load execution DAG (from compiled/ subdirectory)
    dag_path = compiled_dir / "execution_dag.json"
    if not dag_path.exists():
        # Fallback: also check plan_dir root for backward compatibility
        dag_path = plan_dir / "execution_dag.json"
        if not dag_path.exists():
            raise FileNotFoundError(f"execution_dag.json not found in {plan_dir}")
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    atoms = execution_atoms(dag)
    run_scoped_steps = [
        str(atom.get("atom_id", ""))
        for atom in atoms
        if atom.get("execution_scope", "run") == "run" and str(atom.get("atom_id", ""))
    ]

    # Load data manifest if available (from compiled/ subdirectory)
    runs: list[RunContext] = []
    if data_manifest_path is None:
        data_manifest_path = compiled_dir / "data_manifest.json"
        if not data_manifest_path.exists():
            # Fallback: check plan_dir root
            data_manifest_path = plan_dir / "data_manifest.json"

    selection_filters = {
        "subject": participant_labels or [],
        "session": session_labels or [],
        "task": task_labels or [],
        "run": run_labels or [],
    }
    if Path(data_manifest_path).exists():
        manifest = json.loads(Path(data_manifest_path).read_text(encoding="utf-8"))
        seen_run_ids: set[str] = set()
        for sr in manifest.get("subject_session_runs", []):
            if any(labels and sr.get(field) not in labels for field, labels in selection_filters.items()):
                continue
            run_id = _build_run_id(sr, _seen=seen_run_ids)
            runs.append(
                RunContext(
                    run_id=run_id,
                    subject=sr.get("subject", ""),
                    session=sr.get("session", ""),
                    run=sr.get("run", ""),
                    task=sr.get("task", ""),
                    data_path=sr.get("path", ""),
                    relative_path=sr.get("relative_path", ""),
                    size_bytes=int(sr.get("size_bytes", 0)),
                    modified_at=str(sr.get("modified_at", "")),
                    source_file_role=sr.get("source_file_role", ""),
                    events_path=sr.get("events_path", ""),
                    status="planned",
                    planned_steps=run_scoped_steps,
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
            )
    else:
        # No data manifest: create a single placeholder run
        runs.append(
            RunContext(
                run_id="dry-run-placeholder",
                status="planned",
                planned_steps=run_scoped_steps,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
        )

    result = DryRunResult(
        total_runs=len(runs),
        planned_runs=runs,
        summary={
            "dag_nodes": len(atoms),
            "dag_atoms": len(atoms),
            "execution_layers": len(dag.get("execution_layers", [])),
            "selection_filters": selection_filters,
        },
    )

    # Write reports if outdir provided (derivatives-style)
    if outdir is not None:
        outdir = Path(outdir)
        dirs = ensure_derivatives_layout(outdir)

        # Write to derivatives/reports/
        _write_run_report(dirs["reports"], result, plan_dir)
        _write_run_json(dirs["reports"], result, plan_dir)

        # Write run_history.jsonl to logs/
        _append_run_history(dirs["logs"], result)

    return result


def _write_run_report(outdir: Path, result: DryRunResult, plan_dir: Path) -> None:
    """Write run_report.md with summary stats and planned runs table."""

    lines = [
        "# Dry-Run Report",
        "",
        "**Plan directory:** `project://outputs/compiled`",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Summary",
        "",
        f"- **Planned runs:** {result.total_runs}",
        f"- **DAG nodes:** {result.summary.get('dag_nodes', 0)}",
        f"- **DAG atoms:** {result.summary.get('dag_atoms', 0)}",
        f"- **Execution layers:** {result.summary.get('execution_layers', 0)}",
        "",
        "## Planned Runs",
        "",
        "| Run ID | Subject | Session | Task | Run | Source | Bytes | Modified | Status | Planned Steps |",
        "|--------|---------|---------|------|-----|--------|-------|----------|--------|-------|",
    ]
    for run in result.planned_runs:
        lines.append(
            f"| `{run.run_id}` | {run.subject} | {run.session} | "
            f"{run.task} | {run.run} | {run.relative_path} | "
            f"{run.size_bytes} | {run.modified_at} | {run.status} | "
            f"{len(run.planned_steps)} |"
        )
    lines.append("")

    (outdir / "run_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_run_json(outdir: Path, result: DryRunResult, plan_dir: Path) -> None:
    """Write run_report.json with full DryRunResult."""
    data = result.model_dump()
    for run in data.get("planned_runs", []):
        if run.get("relative_path"):
            run["data_path"] = run["relative_path"]
        elif Path(str(run.get("data_path", ""))).is_absolute():
            run["data_path"] = Path(str(run["data_path"])).name
        if Path(str(run.get("events_path", ""))).is_absolute():
            run["events_path"] = Path(str(run["events_path"])).name
    data["plan_dir"] = "project://outputs/compiled"
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    (outdir / "run_report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _append_run_history(logdir: Path, result: DryRunResult) -> None:
    """Append a run entry to run_history.jsonl."""
    logdir.mkdir(parents=True, exist_ok=True)
    path = logdir / "run_history.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_runs": result.total_runs,
        "dag_nodes": result.summary.get("dag_nodes", 0),
        "execution_layers": result.summary.get("execution_layers", 0),
        "runs": [
            {
                **r.model_dump(),
                "data_path": r.relative_path or Path(r.data_path).name,
                "events_path": Path(r.events_path).name if r.events_path else "",
            }
            for r in result.planned_runs
        ],
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
