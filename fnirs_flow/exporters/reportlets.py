"""Reportlet system: run-level, project-level, and package-level reports.

Run-level: per subject/session/run summary (import, QC, preprocessing, artifacts).
Project-level: aggregated summary across all runs (success/failure/QC/risks).
Package-level: combined report for submission/reviewer/reproducibility packages.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def generate_run_reportlet(
    run_ctx: dict[str, Any],
    artifacts: list[dict[str, Any]],
    outdir: Path,
) -> Path:
    """Generate a run-level reportlet (Markdown + JSON) for a single run.

    Args:
        run_ctx: RunContext dict with run_id, subject, session, run, status, etc.
        artifacts: List of artifact dicts for this run.
        outdir: Output directory (typically derivatives/reports/).

    Returns:
        Path to the generated reportlet markdown file.
    """
    outdir.mkdir(parents=True, exist_ok=True)

    run_id = run_ctx.get("run_id", "unknown")
    subject = run_ctx.get("subject", "")
    session = run_ctx.get("session", "")
    run = run_ctx.get("run", "")
    status = run_ctx.get("status", "unknown")

    # Build markdown
    lines = [
        f"# Run Reportlet: {run_id}",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Run Info",
        "",
        f"- **Subject:** {subject}",
        f"- **Session:** {session}",
        f"- **Run:** {run}",
        f"- **Status:** {status}",
        f"- **Steps completed:** {len(run_ctx.get('steps_completed', []))}",
        f"- **Artifacts:** {len(artifacts)}",
        "",
    ]

    if run_ctx.get("errors"):
        lines.append("## Errors")
        lines.append("")
        for err in run_ctx["errors"]:
            lines.append(f"- {err}")
        lines.append("")

    if artifacts:
        lines.append("## Artifacts")
        lines.append("")
        lines.append("| Step | Type | SHA256 |")
        lines.append("|------|------|--------|")
        for a in artifacts:
            sha = a.get("sha256", "")[:12]
            lines.append(f"| {a.get('step_id', '')} | {a.get('artifact_type', '')} | {sha} |")
        lines.append("")

    md_content = "\n".join(lines)
    md_path = outdir / f"{run_id}_reportlet.md"
    md_path.write_text(md_content, encoding="utf-8")

    # Also write JSON version
    json_data = {
        "run_id": run_id,
        "subject": subject,
        "session": session,
        "run": run,
        "status": status,
        "steps_completed": run_ctx.get("steps_completed", []),
        "artifacts": artifacts,
        "errors": run_ctx.get("errors", []),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    json_path = outdir / f"{run_id}_reportlet.json"
    json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")

    return md_path


def generate_project_report(
    runs: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    outdir: Path,
) -> Path:
    """Generate a project-level report summarizing all runs.

    Args:
        runs: List of RunContext dicts.
        risks: List of RiskItem dicts from validation.
        outdir: Output directory.

    Returns:
        Path to the generated project report markdown file.
    """
    outdir.mkdir(parents=True, exist_ok=True)

    total = len(runs)
    successful = sum(1 for r in runs if r.get("status") == "completed")
    failed = sum(1 for r in runs if r.get("status") == "failed")
    pending = sum(1 for r in runs if r.get("status") in ("pending", "planned"))

    fatal_risks = sum(1 for r in risks if r.get("severity") == "fatal")
    high_risks = sum(1 for r in risks if r.get("severity") == "high")

    lines = [
        "# Project Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Summary",
        "",
        f"- **Total runs:** {total}",
        f"- **Successful:** {successful}",
        f"- **Failed:** {failed}",
        f"- **Pending:** {pending}",
        f"- **Fatal risks:** {fatal_risks}",
        f"- **High risks:** {high_risks}",
        "",
    ]

    if runs:
        lines.append("## Runs")
        lines.append("")
        lines.append("| Run ID | Subject | Session | Status | Steps |")
        lines.append("|--------|---------|---------|--------|-------|")
        for r in runs:
            steps = len(r.get("steps_completed", []))
            lines.append(
                f"| {r.get('run_id', '')} | {r.get('subject', '')} | "
                f"{r.get('session', '')} | {r.get('status', '')} | {steps} |"
            )
        lines.append("")

    if risks:
        lines.append("## Risks")
        lines.append("")
        lines.append("| Severity | Domain | Code | Message |")
        lines.append("|----------|--------|------|---------|")
        for r in risks:
            lines.append(
                f"| {r.get('severity', '')} | {r.get('domain', '')} | "
                f"{r.get('code', '')} | {r.get('message', '')[:80]} |"
            )
        lines.append("")

    md_content = "\n".join(lines)
    md_path = outdir / "project_report.md"
    md_path.write_text(md_content, encoding="utf-8")

    # JSON version
    json_data = {
        "summary": {
            "total_runs": total,
            "successful": successful,
            "failed": failed,
            "pending": pending,
            "fatal_risks": fatal_risks,
            "high_risks": high_risks,
        },
        "runs": runs,
        "risks": risks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    json_path = outdir / "project_report.json"
    json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")

    return md_path


def generate_package_report(
    project_report_path: Path,
    run_reportlets: list[Path],
    profile_id: str,
    outdir: Path,
) -> Path:
    """Generate a package-level report combining project summary with run reportlets.

    Args:
        project_report_path: Path to project_report.md.
        run_reportlets: Paths to individual run reportlets.
        profile_id: Package profile (submission/reviewer/reproducibility).
        outdir: Output directory.

    Returns:
        Path to the generated package report markdown file.
    """
    outdir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Package Report",
        "",
        f"**Profile:** {profile_id}",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    # Include project report summary
    if project_report_path.exists():
        project_content = project_report_path.read_text(encoding="utf-8")
        # Extract summary section
        in_summary = False
        for line in project_content.split("\n"):
            if line.startswith("## Summary"):
                in_summary = True
            elif line.startswith("## ") and in_summary:
                in_summary = False
            if in_summary:
                lines.append(line)
        lines.append("")

    # List run reportlets
    if run_reportlets:
        lines.append("## Run Reportlets")
        lines.append("")
        for rp in run_reportlets:
            lines.append(f"- `{rp.name}`")
        lines.append("")

    md_content = "\n".join(lines)
    md_path = outdir / "package_report.md"
    md_path.write_text(md_content, encoding="utf-8")

    return md_path
