"""fnirs-flow CLI: validate, compile, discover, dry-run, run, export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def cmd_validate(args: argparse.Namespace) -> int:
    from fnirs_flow.validation.api import validate_flow

    flow_path = Path(args.flow_json)
    if not flow_path.exists():
        print(f"Error: File not found: {args.flow_json}")
        return 1

    flow_dict = json.loads(flow_path.read_text(encoding="utf-8"))
    report = validate_flow(flow_dict)

    if report.is_valid and not report.has_fatal_risks:
        print(f"Flow '{flow_dict.get('flow_id', 'unknown')}' passed validation.")
        if report.warnings:
            print(f"  Warnings: {len(report.warnings)}")
            for w in report.warnings:
                print(f"    - {w}")
        if report.risks:
            print(f"  Risks: {len(report.risks)}")
            for r in report.risks:
                print(f"    [{r.severity}] {r.message}")
        return 0
    else:
        print("Flow validation FAILED.")
        if report.errors:
            print(f"  Errors ({len(report.errors)}):")
            for e in report.errors:
                print(f"    - {e}")
        if report.risks:
            fatal = [r for r in report.risks if r.severity == "fatal"]
            if fatal:
                print(f"  Fatal risks ({len(fatal)}):")
                for r in fatal:
                    print(f"    - {r.message}")
        return 1


def cmd_compile(args: argparse.Namespace) -> int:
    from fnirs_flow.compiler.compiler import compile_flow

    flow_path = Path(args.flow_json)
    if not flow_path.exists():
        print(f"Error: File not found: {args.flow_json}")
        return 1

    flow_dict = json.loads(flow_path.read_text(encoding="utf-8"))
    result = compile_flow(flow_dict, args.outdir)

    print(f"Compiled flow '{result.flow_graph.flow_id}'")
    print(f"  Flow hash: {result.flow_hash[:16]}...")
    print(f"  Output:    {result.outdir}")
    print(f"  Steps:     {len(result.execution_dag.nodes)}")
    print(f"  Layers:    {len(result.execution_dag.execution_layers)}")
    print()
    print("Generated files:")
    for f in sorted(result.outdir.iterdir()):
        print(f"  {f.name}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from fnirs_flow.data.discovery import discover_dataset

    try:
        manifest = discover_dataset(args.dataset_id, args.outdir)
        compiled_dir = Path(args.outdir) / "compiled"
        print(f"Dataset '{args.dataset_id}' discovered")
        print(f"  Files:      {len(manifest.files)}")
        print(f"  Runs:       {len(manifest.subject_session_runs)}")
        print(f"  Local root: {manifest.local_root}")
        print(f"  Output:     {compiled_dir}")
        if not manifest.files:
            print()
            print("  NOTE: No local files found. Data may need to be downloaded.")
            print(f"  Source: {manifest.source.url}")
        return 0
    except ValueError as e:
        print(f"Error: {e}")
        return 1


def cmd_dry_run(args: argparse.Namespace) -> int:
    from fnirs_flow.execution.engine import dry_run

    try:
        result = dry_run(args.plan_dir, outdir=args.outdir)
        report_path = Path(args.outdir) / "derivatives" / "reports" / "run_report.md"
        print(f"Dry-run complete for '{args.plan_dir}'")
        print(f"  Planned runs: {result.total_runs}")
        print(f"  DAG nodes:    {result.summary.get('dag_nodes', 0)}")
        print(f"  Layers:       {result.summary.get('execution_layers', 0)}")
        print(f"  Report:       {report_path}")
        print()
        for run in result.planned_runs:
            print(f"  [{run.status}] {run.run_id}")
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    """Execute real analysis runs via ExecutionService."""
    from fnirs_flow.execution.service import ExecutionRequest, ExecutionService

    try:
        service = ExecutionService()
        request = ExecutionRequest(
            project_dir=args.plan_dir,
            outdir=args.outdir,
            data_root=getattr(args, "data_root", None),
            participant_labels=getattr(args, "participant_label", []) or [],
            session_labels=getattr(args, "session_label", []) or [],
            run_labels=getattr(args, "run_label", []) or [],
            continue_on_failure=getattr(args, "continue_on_failure", True),
        )
        result = service.execute(request)

        # Print summary
        print(f"Execution complete for '{args.plan_dir}'")
        print(f"  Attempt ID:     {result.attempt_id}")
        print(f"  Total runs:     {result.total_runs}")
        print(f"  Successful:     {result.successful_runs}")
        print(f"  Failed:         {result.failed_runs}")
        print(f"  Skipped:        {result.skipped_runs}")

        if result.failure_ids:
            print(f"  Failure IDs:    {', '.join(result.failure_ids)}")

        outdir = Path(args.outdir) if args.outdir else Path(args.plan_dir)
        summary_path = outdir / "logs" / "execution_summary.json"
        if summary_path.exists():
            print(f"  Summary:        {summary_path}")

        # Print per-run status
        for rr in result.run_results:
            status_icon = {
                "completed": "[OK]",
                "failed": "[FAIL]",
                "skipped": "[SKIP]",
            }.get(rr.status, "[???]")
            print(f"    {status_icon} {rr.run_id}")
            if rr.status == "failed":
                for ar in rr.atom_results:
                    if ar.error:
                        print(f"        Error: {ar.error}")

        return 0 if result.failed_runs == 0 else 1
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_export(args: argparse.Namespace) -> int:
    """Export a compiled project as a .fnirsflow.zip package."""
    from fnirs_flow.exporters.package_exporter import export_package, get_package_profile

    compiled_dir = Path(args.plan_dir)
    if not (compiled_dir / "plan.json").exists():
        # Check if user passed the parent directory
        if (compiled_dir / "compiled" / "plan.json").exists():
            compiled_dir = compiled_dir / "compiled"
        else:
            print(f"Error: No plan.json found in {args.plan_dir}")
            return 1

    profile_id = args.profile
    try:
        profile = get_package_profile(profile_id)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    pkg_name = f"{compiled_dir.parent.name}_package.fnirsflow.zip"
    pkg_path = outdir / pkg_name

    try:
        export_package(compiled_dir, pkg_path, profile_id=profile_id)
        print(f"Package exported: {pkg_path}")
        print(f"  Profile:  {profile.name}")
        print(f"  Size:     {pkg_path.stat().st_size} bytes")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_webui(args: argparse.Namespace) -> int:
    """Start the WebUI server."""
    try:
        import uvicorn

        from fnirs_flow.api.app import app

        host = args.host or "127.0.0.1"
        port = args.port

        if args.dev:
            # Dev mode: start Vite dev server + backend concurrently
            import subprocess
            import sys

            webui_dir = Path(__file__).parent / "webui"
            if not (webui_dir / "node_modules").exists():
                print("Installing frontend dependencies...")
                subprocess.run(["npm", "ci"], cwd=webui_dir, check=True)

            print("Starting fnirs-flow in DEV mode")
            print(f"  Backend:  http://{host}:{port}")
            print("  Frontend: http://localhost:3000")
            print("Press Ctrl+C to stop")

            # Start Vite dev server in background
            vite_proc = subprocess.Popen(
                ["npm", "run", "dev"],
                cwd=webui_dir,
                shell=(sys.platform == "win32"),
            )

            try:
                uvicorn.run(app, host=host, port=port)
            finally:
                vite_proc.terminate()
                vite_proc.wait(timeout=5)
        else:
            # Production mode: serve built frontend from FastAPI
            dist_dir = Path(__file__).parent / "webui" / "dist"
            if not dist_dir.exists():
                print("Frontend not built. Building now...")
                import subprocess

                webui_dir = Path(__file__).parent / "webui"
                if not (webui_dir / "node_modules").exists():
                    print("Installing frontend dependencies...")
                    subprocess.run(["npm", "ci"], cwd=webui_dir, check=True)
                print("Building frontend...")
                subprocess.run(["npm", "run", "build"], cwd=webui_dir, check=True)
                print()

            print(f"Starting fnirs-flow WebUI on http://{host}:{port}")
            print("Press Ctrl+C to stop")
            uvicorn.run(app, host=host, port=port)
        return 0
    except ImportError:
        print("Error: uvicorn is required for WebUI.")
        print("Install with: pip install fnirs-flow[full]")
        return 1


def cmd_rerun(args: argparse.Namespace) -> int:
    """Rerun an imported package after data relink."""
    from fnirs_flow.exporters.package_importer import rerun_package

    try:
        result = rerun_package(
            package_dir=args.package_dir,
            outdir=args.outdir,
            participant_labels=getattr(args, "participant_label", []) or [],
            continue_on_failure=getattr(args, "continue_on_failure", True),
        )
        print(f"Rerun complete for '{args.package_dir}'")
        print(f"  Attempt ID:     {result['attempt_id']}")
        print(f"  Total runs:     {result['total_runs']}")
        print(f"  Successful:     {result['successful_runs']}")
        print(f"  Failed:         {result['failed_runs']}")
        print(f"  Skipped:        {result['skipped_runs']}")
        if result["failure_ids"]:
            print(f"  Failure IDs:    {', '.join(result['failure_ids'])}")
        if result["reports"]:
            print(f"  Reports:        {', '.join(result['reports'])}")
        return 0 if result["failed_runs"] == 0 else 1
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fnirs-flow",
        description="fnirs-flow: evidence-driven fNIRS analysis workflow orchestration",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # User-facing commands
    p_validate = subparsers.add_parser("validate", help="Validate a flow JSON file")
    p_validate.add_argument("flow_json", help="Path to flow JSON file")
    p_validate.set_defaults(func=cmd_validate)

    p_compile = subparsers.add_parser("compile", help="Compile flow to plan/dag/manifests")
    p_compile.add_argument("flow_json", help="Path to flow JSON file")
    p_compile.add_argument("--outdir", required=True, help="Output directory")
    p_compile.set_defaults(func=cmd_compile)

    p_discover = subparsers.add_parser("discover", help="Discover a public dataset")
    p_discover.add_argument("dataset_id", help="Dataset identifier")
    p_discover.add_argument("--outdir", required=True, help="Output directory")
    p_discover.set_defaults(func=cmd_discover)

    p_dryrun = subparsers.add_parser("dry-run", help="Dry-run a compiled plan")
    p_dryrun.add_argument("plan_dir", help="Directory with compiled plan (or parent dir)")
    p_dryrun.add_argument("--outdir", required=True, help="Output directory")
    p_dryrun.set_defaults(func=cmd_dry_run)

    p_run = subparsers.add_parser("run", help="Execute analysis runs via adapter")
    p_run.add_argument("plan_dir", help="Directory with compiled plan (or parent dir)")
    p_run.add_argument("--outdir", required=True, help="Output directory")
    p_run.add_argument("--data-root", help="Root directory containing BIDS-NIRS data")
    p_run.add_argument("--participant-label", nargs="*", help="Filter by participant label")
    p_run.add_argument("--session-label", nargs="*", help="Filter by session label")
    p_run.add_argument("--run-label", nargs="*", help="Filter by run label")
    p_run.add_argument(
        "--continue-on-failure",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Continue processing other runs if one fails (default: True). "
        "Use --no-continue-on-failure to stop on first failure.",
    )
    p_run.set_defaults(func=cmd_run)

    p_export = subparsers.add_parser("export", help="Export compiled project as package")
    p_export.add_argument("plan_dir", help="Directory with compiled plan (or parent dir)")
    p_export.add_argument("--outdir", required=True, help="Output directory for package")
    p_export.add_argument(
        "--profile",
        default="reproducibility_package",
        choices=["reproducibility_package", "submission_package", "reviewer_package"],
        help="Package profile (default: reproducibility_package)",
    )
    p_export.set_defaults(func=cmd_export)

    p_rerun = subparsers.add_parser("rerun", help="Rerun an imported package after data relink")
    p_rerun.add_argument("package_dir", help="Directory containing the imported package")
    p_rerun.add_argument("--outdir", default=None, help="Output directory (defaults to package_dir)")
    p_rerun.add_argument("--participant-label", nargs="*", help="Filter by participant label")
    p_rerun.add_argument(
        "--continue-on-failure",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Continue on failure (default: True)",
    )
    p_rerun.set_defaults(func=cmd_rerun)

    p_webui = subparsers.add_parser("webui", help="Start the WebUI server")
    p_webui.add_argument("--host", default=None, help="Host to bind to (default: 127.0.0.1)")
    p_webui.add_argument("--port", type=int, default=8000, help="Port to listen on")
    p_webui.add_argument("--dev", action="store_true", help="Dev mode: start Vite dev server alongside backend")
    p_webui.set_defaults(func=cmd_webui)

    # Legacy aliases (backward compatibility)
    p_validate_legacy = subparsers.add_parser("validate-flow", help="[Deprecated] Use 'validate'")
    p_validate_legacy.add_argument("flow_json", help="Path to flow JSON file")
    p_validate_legacy.set_defaults(func=cmd_validate)

    p_compile_legacy = subparsers.add_parser("compile-flow", help="[Deprecated] Use 'compile'")
    p_compile_legacy.add_argument("flow_json", help="Path to flow JSON file")
    p_compile_legacy.add_argument("--outdir", required=True, help="Output directory")
    p_compile_legacy.set_defaults(func=cmd_compile)

    p_discover_legacy = subparsers.add_parser("discover-dataset", help="[Deprecated] Use 'discover'")
    p_discover_legacy.add_argument("dataset_id", help="Dataset identifier")
    p_discover_legacy.add_argument("--outdir", required=True, help="Output directory")
    p_discover_legacy.set_defaults(func=cmd_discover)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
